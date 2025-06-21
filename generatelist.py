import robin_stocks.robinhood as rh
from predict_stock import run_lstm
from predict_stock_granular import run_lstm_granular
import pandas as pd
import logging
from datetime import datetime, timedelta
import time
import argparse
import logging
import time
import requests
import os
import json, re, sys
from hashlib import md5
from pathlib import Path
import pandas as pd
import requests
import yfinance as yf
import boto3
import base64, getpass, os, random, uuid, time, sys, requests
from pathlib import Path
from typing import Dict, List

import os, logging, requests, pandas as pd
from datetime import datetime, timedelta, timezone

import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

import pandas as pd
import requests
from pandas.errors import EmptyDataError

def get_top_52w_gainers(limit: int = 100, group: str = "52-week-gainers") -> list[str]:
    """
    DAY_GAINERS, DAY_LOSERS, MOST_ACTIVES
    FIFTY_TWO_WK_GAINERS, FIFTY_TWO_WK_LOSERS UNUSUAL_VOLUME, MOST_SHORTED_STOCKS, TOP_VOLUME_ETFS
    # filters exactly as you wrote them
    most_actives = [
        ["eq",   ["region",            "us"     ]],      # region = US
        ["btwn", ["intradaymarketcap", 2e9, 1e11]],      # $2 B – $100 B
        ["gt",   ["dayvolume",         5e6      ]]       # vol > 5 M
    ]

    resp = yf.screen(query=most_actives, count=25, sortField="dayvolume", sortType="desc")
    tickers = [q["symbol"] for q in resp["quotes"]]
    print(tickers)
    """
    resp = yf.screen("FIFTY_TWO_WK_GAINERS", count=100)   # ← returns JSON dict
    tickers = [row["symbol"] for row in resp["quotes"]] 

    
    return tickers



def get_parameter_value(parameter_name):

    ssm_client = boto3.client('ssm')

    try:
        logging.info(f"getting parameter {parameter_name}")
        response = ssm_client.get_parameter(Name=parameter_name)
        return response['Parameter']['Value']

    except ssm_client.exceptions.ParameterNotFound:
        logging.info(f"Parameter '{parameter_name}' not found.")
        return None

    except Exception as e:
        print(f"Error occurred in getting parameters: {str(e)}")
        return None



def getWeightedAverage(stock):
    data = rh.stocks.get_stock_historicals(stock,interval="10minute", span="day")
        
    data_hour = data[-10:]
    combined = data + data_hour

    df = pd.DataFrame(combined)
    
    # Convert prices to numeric values
    df['open_price'] = pd.to_numeric(df['open_price'])
    df['close_price'] = pd.to_numeric(df['close_price'])
    df['high_price'] = pd.to_numeric(df['high_price'])
    df['low_price'] = pd.to_numeric(df['low_price'])


    avg_open = df['open_price'].mean()
    avg_close = df['close_price'].mean()
    # avg_high = df['high_price'].mean()
    # avg_low = df['low_price'].mean()
    dayaverage = (avg_open + avg_close)/2 
    return(dayaverage)




def get_parameter_value(parameter_name):

    ssm_client = boto3.client('ssm')

    try:
        logging.info(f"getting parameter {parameter_name}")
        response = ssm_client.get_parameter(Name=parameter_name)
        return response['Parameter']['Value']

    except ssm_client.exceptions.ParameterNotFound:
        print(f"Parameter '{parameter_name}' not found.")
        return None

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return None
    


def update_price_data(
    symbol: str,
    alpaca_api_key: str,
    alpaca_secret_key: str,
    interval: str = "minute",
    interval_multiplier: int = 15,
    lookback_days: int = 7,
    limit: int = 1000,
) -> Tuple[pd.DataFrame, float, float]:
    """
    Fetch new OHLCV bars for *symbol* from Alpaca, merge with data/<SYMBOL>_prices.csv,
    deduplicate, resave, and return:
        (df_updated, lowest_price, highest_price)
    """

    # ---- 1. Timeframe string ----
    UNIT_MAP = {
        "minute": "Min", "min": "Min", "t": "T",
        "hour": "Hour", "h": "H",
        "day": "Day", "d": "D",
        "week": "Week", "w": "W",
        "month": "Month", "m": "M",
    }
    if interval.lower() not in UNIT_MAP:
        raise ValueError(f"Unsupported interval: {interval}")
    timeframe = f"{interval_multiplier}{UNIT_MAP[interval.lower()]}"

    # ---- 2. Load existing CSV (defensive) ----
    csv_path = Path("data") / f"{symbol}_prices.csv"
    try:
        df_existing = pd.read_csv(csv_path, parse_dates=["timestamp"])
        df_existing["timestamp"] = pd.to_datetime(df_existing["timestamp"], utc=True)
        df_existing.sort_values("timestamp", inplace=True)
        last_date = df_existing["timestamp"].max().date()
        start_dt = datetime.combine(last_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    except (FileNotFoundError, EmptyDataError, KeyError, ValueError) as e:
        logging.warning("Could not load existing CSV for %s: %s", symbol, e)
        df_existing = pd.DataFrame()
        start_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=lookback_days)

    end_dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- 3. API call ----
    url_base = (
        f"https://data.alpaca.markets/v2/stocks/bars"
        f"?symbols={symbol}&timeframe={timeframe}&start={start_iso}&end={end_iso}"
        f"&limit={limit}&adjustment=raw&feed=sip&sort=asc"
    )
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": alpaca_api_key,
        "APCA-API-SECRET-KEY": alpaca_secret_key,
    }

    all_new_bars, next_page = [], None
    while True:
        url = url_base + (f"&page_token={next_page}" if next_page else "")
        resp = requests.get(url, headers=headers, timeout=30).json()
        all_new_bars.extend(resp.get("bars", {}).get(symbol, []))
        next_page = resp.get("next_page_token")
        if not next_page:
            break

    # ---- 4. Normalize and merge ----
    if all_new_bars:
        df_new = pd.DataFrame(all_new_bars).rename(columns={"t": "timestamp"})
        df_new["timestamp"] = pd.to_datetime(df_new["timestamp"], utc=True)
        df_new.sort_values("timestamp", inplace=True)

        # Normalize Alpaca columns
        RENAME = {"o": "o", "h": "h", "l": "l", "c": "c", "v": "v"}
        df_new.rename(columns={k: v for k, v in RENAME.items() if k in df_new.columns}, inplace=True)

        # Merge
        df_updated = (
            pd.concat([df_existing, df_new], ignore_index=True)
            .drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
        )

        # Normalize merged DataFrame too
        df_updated.rename(columns={k: v for k, v in RENAME.items() if k in df_updated.columns}, inplace=True)
        df_updated["timestamp"] = pd.to_datetime(df_updated["timestamp"], utc=True)
    else:
        logging.info("No new bars returned by Alpaca")
        df_updated = df_existing

    # ---- 5. Save to CSV ----
    if not df_updated.empty and all_new_bars:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df_updated.to_csv(csv_path, index=False)
        logging.info("Saved updated data to %s", csv_path)

    # ---- 6. Compute low/high over lookback period ----
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recent = df_updated[df_updated["timestamp"] >= cutoff]

    logging.info("Recent sample for %s:\n%s", symbol, recent.tail(3).to_string())
    logging.info("Columns present: %s", recent.columns.tolist())
    logging.info("Cutoff: %s", cutoff)

    try:

        lowest_price = float(recent["l"].min()) if "l" in recent.columns and not recent.empty else float("nan")
        highest_price = float(recent["h"].max()) if "h" in recent.columns and not recent.empty else float("nan")
    except Exception as e:
        logging.error("Error calculating high/low for %s: %s", symbol, e)
        lowest_price, highest_price = float("nan"), float("nan")

    logging.info("%s range over last %d days: %.2f ↔ %.2f", symbol, lookback_days, lowest_price, highest_price)

    return df_updated, lowest_price, highest_price



# (Keep getAllTrades as is, it's fine after update_price_data is fixed)
def getAllTrades(
    group: str,
    alpaca_api_key: str,
    alpaca_secret_key: str,
    *,
    interval: str = "minute",
    interval_multiplier: int = 5,
    lookback_days_for_range: int = 7,
) -> list[str]:
    """
    Return a list of the top 20 tickers (price < $200) within *group*
    ranked by the difference between their 7-day high and 7-day low price.

    Bars are pulled in 5‑minute buckets via update_price_data().
    """
    movers: list[tuple[str, float]] = []
    stockList: list[str] = []

    logging.info("Calculating top movers based on %d-day price range", lookback_days_for_range)

   

    tickers = get_top_52w_gainers(limit=100, group=group)
    if not tickers:
        logging.warning("No tickers found for category '%s'", group)
        return []

    for symbol in tickers:
        try:
            df, week_low, week_high = update_price_data(
                symbol,
                alpaca_api_key,
                alpaca_secret_key,
                interval=interval,
                interval_multiplier=interval_multiplier,
                lookback_days=lookback_days_for_range,
            )

            if df.empty:
                logging.warning("No data for %s", symbol)
                continue

            # Check if the highest price in the range is under $200
            if pd.isna(week_high) or week_high >= 200:
                logging.info(f"{symbol} (High: {week_high:.2f}) is not under $200 or has no valid high/low. Skipping.")
                continue

            price_range = week_high - week_low
            
            if price_range > 0: # Ensure there's actual movement
                movers.append((symbol, price_range))
                logging.debug(
                    "%s — %d-day low: %.2f  high: %.2f  range: %.2f",
                    symbol, lookback_days_for_range, week_low, week_high, price_range
                )

        except Exception as exc:
            logging.error("getAllTrades: error processing %s — %s", symbol, exc)

    # rank by price range, descending
    movers.sort(key=lambda x: x[1], reverse=True)

    # Return top 20 symbols
    for sym, diff in movers[:20]:
        logging.info("%s %d-day price range: %.2f", sym, lookback_days_for_range, diff)
        stockList.append(sym)

    return stockList


def get_latest_prices(
    symbols: List[str],
    alpaca_api_key: str,
    alpaca_secret_key: str,
    timeout: int = 10
) -> Dict[str, float]:
    """
    Fetch the latest bar for each symbol from Alpaca and return a
    dict of {ticker: latest_close_price}.
    """
    # Build query string (Alpaca accepts comma‑separated list)
    url = (
        "https://data.alpaca.markets/v2/stocks/bars/latest"
        f"?symbols={','.join(symbols)}"
    )

    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": alpaca_api_key,
        "APCA-API-SECRET-KEY": alpaca_secret_key,
    }

    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()          # raises on HTTP errors

    bars = response.json().get("bars", {})
    # Extract the `"c"` (close) price for each ticker
    latest_prices = {ticker: info["c"] for ticker, info in bars.items()}

    return latest_prices


def load_config(config_path: str = "parameters.config") -> dict:
    """
    Loads a config file with key=value pairs (ignoring comments and blank lines),
    assigns variables to the values, and returns a dictionary of the config.
    """
    config = {}
    if not os.path.exists(config_path):
        logging.warning(f"Config file {config_path} not found.")
        return config
    with open(config_path, 'r') as f:
        for line in f:
            # Remove comments and strip whitespace
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # Try to convert to int or float if possible
                if value.isdigit():
                    value = int(value)
                else:
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                config[key] = value
                # Assign variable in local scope (not global)
                locals()[key] = value
    return config


def main():
    try:
        
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        logging.basicConfig(filename=f'logs/{current_date}-generator.log', level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')


        logging.info(f"-------------------------------------------------------------------------------------------------\n\n")
        parser = argparse.ArgumentParser(description='Trading bot configuration')
        parser.add_argument('-g', '--group', type=str, required=True, 
                          help='The group of stocks to trade (biopharmaceutical, upcoming-earnings, most-popular-under-25, technology)')
        
       

        args = parser.parse_args()
        logging.info(f"args are {args}")
        logging.info(f"getting alpaca api key")
        alpaca_api_key = get_parameter_value("/alpaca/key")
        logging.info(f"getting alpaca secret key")
        alpaca_secret_key = get_parameter_value("/alpaca/secret")
        
        
        config = load_config()
        for key, value in config.items():
            globals()[key] = value
    


    

        
        starthour = 9
        #login()

        # response = rh.markets.get_all_stocks_from_market_tag("technology")
        # print(response)
        logging.info(f"time now is {datetime.now()}")
        if datetime.now().hour > starthour:
            logging.info(f"time now is {datetime.now()} and past the market start time running this in dry run")
            sampleTrade = getAllTrades(args.group, alpaca_api_key, alpaca_secret_key)
            logging.info(f"these are the stocks we are trading{sampleTrade}")
            #run_lstm("NVDA")
            for stock_id in sampleTrade:
                latest_price = get_latest_prices([stock_id], alpaca_api_key, alpaca_secret_key)
                predicted_price = run_lstm(stock_id, base_dir="data", epochs=50, show_plot=False)
                
                if latest_price.get(stock_id) > predicted_price:
                    logging.info(f"Predicted price of {stock_id} is less than latest price. moving to the next stock")
                    continue
                df, week_low, week_high = update_price_data(
                stock_id,
                alpaca_api_key=alpaca_api_key,
                alpaca_secret_key=alpaca_secret_key,
                interval="minute",
                interval_multiplier=15,
                lookback_days=7,
                )            
                if latest_price.get(stock_id) < (0.1 * (week_high - week_low)) + week_low:
                    logging.info(f"{stock_id} is not in the lowest it has been all week. skipping to the next")
                if latest_price.get(stock_id) < predicted_price and latest_price.get(stock_id) < (0.1 * (week_high - week_low)) + week_low:
                    logging.info(f"Predicted price of {stock_id} is greater than latest price. We will trade this")
                    logging.info(f"writing the stock {stock_id} into a csv")
                    with open(f'{current_date}-stocks-to-trade.csv', 'a') as file:
                        file.write(f"{stock_id},")
            time.sleep(2)
        while datetime.now().hour < starthour:
            logging.info(f" time is {datetime.now()}")
            
            sampleTrade = getAllTrades(args.group, alpaca_api_key, alpaca_secret_key)
            logging.info(f"these are the stocks we are trading{sampleTrade}")
            #run_lstm("NVDA")
            for stock_id in sampleTrade:
                latest_price = get_latest_prices([stock_id], alpaca_api_key, alpaca_secret_key)
                predicted_price = run_lstm(stock_id, base_dir="data", epochs=50, show_plot=False)
                
                if latest_price.get(stock_id) > predicted_price:
                    logging.info(f"Predicted price of {stock_id} is less than latest price. moving to the next stock")
                    continue
                df, week_low, week_high = update_price_data(
                stock_id,
                alpaca_api_key=alpaca_api_key,
                alpaca_secret_key=alpaca_secret_key,
                interval="minute",
                interval_multiplier=15,
                lookback_days=7,
                )    
                if latest_price.get(stock_id) < (0.1 * (week_high - week_low)) + week_low:
                    logging.info(f"{stock_id} is not in the lowest it has been all week. skipping to the next")
                if latest_price.get(stock_id) < predicted_price and latest_price < (0.1 * (week_high - week_low)) + week_low:
                    logging.info(f"Predicted price of {stock_id} is greater than latest price. We will trade this")
                    logging.info(f"writing the stock {stock_id} into a csv")
                    with open(f'{current_date}-stocks-to-trade.csv', 'a') as file:
                        file.write(f"{stock_id},")
            time.sleep(2)
    except Exception as e:
        logging.error(f"Tradinng bot generator failed: {str(e)}")
        return False
       

if __name__ == '__main__':  
    main()
