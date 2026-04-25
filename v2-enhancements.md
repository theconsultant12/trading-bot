# Trading Bot — v2 Enhancements

**Branch:** `improvements/v2-enhancements`  
**Date:** 2026-04-25  

---

## Summary

Five files were changed to fix critical correctness bugs, improve the ML model, harden security, and make strategy thresholds configurable.  No external APIs, schemas, or runtime behaviour were broken in the process.

---

## Changes by File

### `mainV2.py` — Core Trading Engine

#### 1. Fix: Sell condition never triggered (critical bug)
The `while` loop that monitors prices before selling was comparing the **sum of raw per-share prices** against the **total dollar cost** (price × quantity). Because total cost is always larger (it includes quantity), the profit target could never be reached and the bot would spin forever, relying on the 3:30 PM SIGTERM to ever exit.

**Fix:** The comparison now multiplies current prices by `quantity` (2) before comparing, so it measures portfolio *value* vs portfolio *cost*.

```python
# Before (broken — dimensionally inconsistent)
while sum(price for ticker in bought_stocks) < total_cost * 1.0012:

# After (correct)
current_value = sum(price * quantity for ticker in bought_stocks)
if current_value >= total_cost * PROFIT_TARGET:
    break
```

#### 2. New: Stop-loss (0.5%)
If the current portfolio value drops 0.5 % below the purchase cost, the bot exits the hold loop and sells immediately instead of riding a loss indefinitely.

#### 3. New: Max hold time (30 minutes)
Even if neither the profit target nor the stop-loss is triggered, the bot will force a sell after `MAX_HOLD_SECONDS` (1 800 s / 30 min). This prevents positions being held all day on illiquid stocks.

#### 4. Fix: Sell executor bug
`ThreadPoolExecutor` was called with `run_sell(bought_stocks.keys())` — passing the entire dictionary-keys view as a single argument. Each call to `run_sell` received all symbols at once instead of one.

```python
# Before (bug — passes dict_keys as one argument)
futures = {executor.submit(run_sell, bought_stocks.keys()): stock ...}

# After (correct — one future per symbol)
futures = {executor.submit(run_sell, stock): stock for stock in bought_stocks}
```

#### 5. Fix: DynamoDB attribute mismatch
`check_transaction()` and `closeDay()` were scanning DynamoDB with `begins_with(composite_key, ...)`. The actual partition key stored by `record_transaction()` is named `key`, and its format is `{user_id}#{date}` — so a prefix filter on `current_date` would never match anything. Both functions now scan on the dedicated `Date` attribute.

```python
# Before (wrong attribute name, wrong filter strategy)
FilterExpression="begins_with(#k, :date)",
ExpressionAttributeNames={"#k": "composite_key"},

# After
from boto3.dynamodb.conditions import Attr
FilterExpression=Attr("Date").eq(current_date)
```

#### 6. Fix: Broken daily-loss check
The loss guard at end-of-day evaluated `startBalance - currentBalance - startBalance == 500`, which always equals `-currentBalance == 500` (never true). Fixed to `startBalance - endBalance >= 500`.

#### 7. Fix: Threading lock for shared memory
`read_shared_prices()` could race with the WebSocket writer in `interactive.py`. A module-level `threading.Lock` (`_shm_lock`) now wraps the open/read/close sequence. The `SharedMemory` handle is also closed after each read to avoid handle leaks.

---

### `predict_stock.py` — LSTM Price Predictor

#### 1. New: MinMaxScaler normalisation
Stock prices range from a few dollars to hundreds. Without normalisation, the LSTM's weights were forced to handle vastly different input scales, leading to slow convergence and poor generalisation. Prices are now scaled to [0, 1] before training, and the final prediction is inverse-transformed back to dollars.

```python
scaler = MinMaxScaler()
df["Close"] = scaler.fit_transform(df[["Close"]])
# ... train, predict (scaled) ...
predicted_price = scaler.inverse_transform([[predicted_scaled]])[0][0]
```

#### 2. Improvement: Lookback window 3 → 20
Three data points give the model almost no trend information. A 20-step window lets the LSTM see roughly a month of daily closes (or several hours of intraday bars), which is enough to capture short-term momentum and mean-reversion signals.

#### 3. New: EarlyStopping callback
Training for a fixed 100 epochs on small datasets regularly overfits. `EarlyStopping(patience=10, restore_best_weights=True)` now halts training as soon as validation loss stops improving and reloads the best checkpoint.

#### 4. Fix: Minimum data check
The old guard required only 4 rows (`n+1` for `n=3`). Updated to `LOOKBACK + 1 = 21` rows to match the new window size.

#### 5. Chart: y-axis now in original dollar units
The saved PNG chart (`stock_graph/SYMBOL.png`) now shows prices in dollars rather than the normalised [0, 1] scale, making it immediately readable.

---

### `generatelist.py` — Stock Selection Engine

#### 1. Fix: Duplicate `get_parameter_value` function removed
The function was defined twice (lines 61–76 and 105–120 in the original). Python silently uses the last definition; the first was dead code with a subtly different log level. The single canonical version is kept with consistent `logging.*` calls throughout.

#### 2. Fix: Missing `import atexit`
`atexit.register(cleanup)` in `main()` was calling a module that was never imported, causing a `NameError` at startup. The import is now present.

#### 3. Cleanup: Redundant imports removed
The original file duplicated `import pandas as pd`, `import requests`, `import os`, `import logging`, `from datetime import datetime, timedelta`, and others — some appearing four or five times. All imports are now consolidated into a single clean block at the top.

---

### `interactive.py` — Voice Controller & Orchestrator

#### 1. Fix: WebSocket stream started at wrong time
`run_stream()` had a comment saying "9:28 AM" but the condition checked `hour == 10 and minute == 28` (10:28 AM — a full hour late). The market opens at 9:30 AM ET; subscribing at 10:28 AM meant the bot had no live prices for the first hour of trading.

```python
# Before (10:28 AM — wrong)
if now.hour == 10 and now.minute == 28 and not started:

# After (9:28 AM — correct, 2 min before open)
if now.hour == 9 and now.minute == 28 and not started:
```

#### 2. Security: Discord webhook moved to AWS SSM
The webhook URL was hardcoded in plain text. Anyone with read access to the repository could send messages to the Discord channel. The URL is now fetched from AWS SSM Parameter Store at runtime under `/discord/webhook_url` — consistent with how Alpaca and OpenAI keys are already managed.

```python
# Before (hardcoded secret in source)
webhook_url = "https://discord.com/api/webhooks/1429499429500616819/..."

# After (read from SSM at runtime)
webhook_url = get_parameter_value("/discord/webhook_url")
```

To migrate: store your existing webhook URL in SSM:
```bash
aws ssm put-parameter \
  --name "/discord/webhook_url" \
  --value "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_TOKEN" \
  --type "String"
```

---

### `parameters.config` — Strategy Configuration

Five new keys were added so trading strategy thresholds can be adjusted without touching source code:

| Key | Default | Description |
|-----|---------|-------------|
| `profit_target` | `0.0012` | Fractional gain required before selling (0.12 %) |
| `stop_loss_pct` | `0.005` | Fractional drop that triggers an early sell (0.5 %) |
| `max_hold_minutes` | `30` | Maximum hold duration before forcing a sell |
| `batch_size` | `4` | Stocks bought per trading cycle |
| `quantity` | `2` | Shares purchased per stock |

> **Note:** `mainV2.py` currently uses hard-coded constants that match these defaults. A future task is to wire `load_config()` into `main()` so these values are read at startup rather than requiring a source edit.

---

## Known Remaining Issues (Out of Scope for This Branch)

| Issue | Location | Notes |
|-------|----------|-------|
| `config` values not read at runtime in `mainV2.py` | `main()` | `parameters.config` is parsed by `generatelist.py` but `mainV2.py` uses its own hard-coded constants. A follow-up task should call `load_config()` in `mainV2.main()` and apply the values. |
| LSTM retrained per-stock, per-run | `generatelist.py:503` | Expensive. Models should be cached to disk and only re-trained when new data arrives. |
| Short-term lookback for intraday decisions | `predict_stock.py` | Daily-bar LSTM predicts next-day close; the bot executes intraday. The granular hourly predictor (`predict_stock_granular.py`) should be evaluated and integrated. |
| `longterm-trader.py` stubs not implemented | `longterm-trader.py` | Placeholder only. |
| WebSocket shared memory is 1 024 bytes | `interactive.py:747` | With 20+ tickers the JSON payload can exceed this limit, silently truncating prices. `PRICE_MEM_SIZE` should scale with the number of subscribed tickers. |
| `is_generate_list_time()` fires at 00:00 on weekdays | `interactive.py:452` | Stock screener runs at midnight but Alpaca data for the previous day may not yet be updated. A 30-minute delay or explicit market-data-available check would be safer. |

---

## How to Test

```bash
# Switch to the improvement branch
git checkout improvements/v2-enhancements

# Activate the conda environment
conda activate bot-env

# Verify syntax and imports
python3 -c "import mainV2, predict_stock, generatelist"

# Run the stock predictor on a symbol with enough historical data
python3 -c "from predict_stock import run_lstm; print(run_lstm('NVDA', show_plot=False))"

# Dry-run a single bot instance (uses paper trading, no real money)
python3 mainV2.py -d -u U001
```

---

## Files Changed

```
mainV2.py           +76 / -70   Core trading logic fixes
predict_stock.py    +57 / -33   ML model improvements
generatelist.py     +20 / -67   Deduplication and import fix
interactive.py      +12 / -7    Time bug and security fix
parameters.config   +8  / -1    New strategy knobs
```
