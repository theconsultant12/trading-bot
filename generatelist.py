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
from typing import Dict

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

def login():
    """Login using stored token or notify if reauth needed"""
    try:
        username = get_parameter_value('/robinhood/username')
        password = get_parameter_value('/robinhood/password')
            # Try to use existing token
        response = rh.authentication.login(
            username=username,
            password=password,
            expiresIn=3600*24,
            scope='internal',
            store_session=True,
            mfa_code=None,
        )
        logging.info("Login successful using stored token")
        return True

        
    except Exception as e:
        logging.error(f"Login failed: {str(e)}")
        return False
    
def getCurrentBalance():
    global DAYCOUNT 
    DAYCOUNT += 1
    try:
        return float(rh.profiles.load_portfolio_profile().get('withdrawable_amount'))
    except Exception as e:
        logging.error(f"Error in getCurrentBalance: {str(e)}")
        return 0.0

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
    interval: str = "minute",          # timeframe unit
    interval_multiplier: int = 15,     # e.g. 15‑minute candles
    lookback_days: int = 7,            # how far back on first run
    limit: int = 1000,
) -> Tuple[pd.DataFrame, float, float]:
    """
    Fetch new OHLCV bars for *symbol* from Alpaca, merge with data/<SYMBOL>_prices.csv,
    deduplicate, resave, and return:

        (df_updated, lowest_price, highest_price)

    • Uses Alpaca’s native column names: c, h, l, n, o, v, vw
    • lowest/highest are computed over the last *lookback_days*.
    """

    # ---- 1. Build Alpaca timeframe string (“15Min” etc.) --------------------
    UNIT_MAP = {
        "minute": "Min", "min": "Min", "t": "T",
        "hour":   "Hour", "h": "H",
        "day":    "Day",  "d": "D",
        "week":   "Week", "w": "W",
        "month":  "Month", "m": "M",
    }
    if interval.lower() not in UNIT_MAP:
        raise ValueError(f"Unsupported interval: {interval}")
    timeframe = f"{interval_multiplier}{UNIT_MAP[interval.lower()]}"  # “15Min”

    # ---- 2. Determine start date -------------------------------------------
    csv_path = Path("data") / f"{symbol}_prices.csv"
    try:
        df_existing = pd.read_csv(csv_path, parse_dates=["timestamp"])
        df_existing.sort_values("timestamp", inplace=True)
        last_date = df_existing["timestamp"].max().date()
        start_dt = datetime.combine(
            last_date + timedelta(days=1),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    except (FileNotFoundError, EmptyDataError):
        df_existing = pd.DataFrame()
        start_dt = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            - timedelta(days=lookback_days)
        )

    end_dt = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_iso, end_iso = (
        start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # ---- 3. Call Alpaca ------------------------------------------------------
    url_base = (
        "https://data.alpaca.markets/v2/stocks/bars"
        f"?symbols={symbol}"
        f"&timeframe={timeframe}"
        f"&start={start_iso}"
        f"&end={end_iso}"
        f"&limit={limit}"
        "&adjustment=raw&feed=sip&sort=asc"
    )
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": alpaca_api_key,
        "APCA-API-SECRET-KEY": alpaca_secret_key,
    }

    all_new_bars, next_page = [], None
    while True:
        url = url_base + (f"&page_token={next_page}" if next_page else "")
        payload = requests.get(url, headers=headers, timeout=30).json()
        all_new_bars.extend(payload.get("bars", {}).get(symbol, []))
        next_page = payload.get("next_page_token")
        if not next_page:
            break

    # ---- 4. Combine ----------------------------------------------------------
    if all_new_bars:
        df_new = pd.DataFrame(all_new_bars).rename(columns={"t": "timestamp"})
        df_new["timestamp"] = pd.to_datetime(df_new["timestamp"])
        df_new.sort_values("timestamp", inplace=True)

        df_updated = (
            pd.concat([df_existing, df_new], ignore_index=True)
            .drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
        )
    else:
        logging.info("No new bars returned by Alpaca")
        df_updated = df_existing

    # ---- 5. Save -------------------------------------------------------------
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df_updated.to_csv(csv_path, index=False)
    logging.info("Saved updated data to %s", csv_path)

    # ---- 6. Compute low/high over recent window -----------------------------
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    recent = df_updated[df_updated["timestamp"] >= cutoff]

    lowest_price = float(recent["l"].min()) if not recent.empty else float("nan")
    highest_price = float(recent["h"].max()) if not recent.empty else float("nan")

    logging.info(
        "%s range over last %d days: %.2f ↔ %.2f",
        symbol, lookback_days, lowest_price, highest_price,
    )

    return df_updated, lowest_price, highest_price




def getAllTrades(
    group: str,
    alpaca_api_key: str,
    alpaca_secret_key: str,
    *,
    interval: str = "minute",
    interval_multiplier: int = 5,
    lookback_hours: int = 36,
) -> list[str]:
    """
    Return a list of the top‑moving tickers (price < $200) within *group*
    over the last `lookback_hours` (default: 1 hour), ranked by the absolute
    move between the first open and last close in that window.

    Bars are pulled in 5‑minute buckets via update_price_data().
    """
    movers: list[tuple[str, float]] = []
    stockList: list[str] = []

    logging.info("Calculating top movers over the last %d hours", lookback_hours)

    tickers = get_top_52w_gainers(limit=100, group=group)
    if not tickers:
        logging.warning("No tickers found for category '%s'", group)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    for symbol in tickers:
        try:
            # pull / update 5‑minute bars for this symb
            df, week_low, week_high = update_price_data(
                symbol,
                alpaca_api_key,
                alpaca_secret_key,
                interval=interval,
                interval_multiplier=interval_multiplier,
                lookback_days=1,      # just in case no CSV exists yet
            )

            if df.empty:
                logging.warning("No data for %s", symbol)
                continue

            # keep only bars within the look‑back window
            df_recent = df[df["timestamp"] >= cutoff]
            if df_recent.empty:
                logging.info("%s has no bars in the last %d hours", symbol, lookback_hours)
                continue

            # Alpaca columns:  o (open)  c (close)
            start_price = df_recent.iloc[0]["o"]
            end_price   = df_recent.iloc[-1]["c"]
            movement    = abs(end_price - start_price)

            logging.debug(
                "%s — start: %.2f  end: %.2f  move: %.2f",
                symbol, start_price, end_price, movement
            )

            if start_price < 200 and movement > 0:
                movers.append((symbol, movement))

        except Exception as exc:
            logging.error("getAllTrades: error processing %s — %s", symbol, exc)

    # rank by movement, descending
    movers.sort(key=lambda x: x[1], reverse=True)

    for sym, diff in movers[:5]:      # top 5
        logging.info("%s moved %.2f", sym, diff)
        stockList.append(sym)

    return stockList

import requests
from typing import List, Dict

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
        
        

        finhub_key = get_parameter_value("finhub_api_key")
    

        
        starthour = 9
        #login()

        # response = rh.markets.get_all_stocks_from_market_tag("technology")
        # print(response)
        logging.info(f"time now is {datetime.now()}")
        if datetime.now().hour > starthour:
            logging.info(f"time now is {datetime.now()} and past the market start time running this in dry run")
            sampleTrade = getAllTrades(args.group, alpaca_api_key, alpaca_secret_key, lookback_hours=360)
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
                if latest_price < (0.1 * (week_high - week_low)) + week_low:
                    logging.info(f"{stock_id} is not in the lowest it has been all week. skipping to the next")
                if latest_price < predicted_price and latest_price < (0.1 * (week_high - week_low)) + week_low:
                    logging.info(f"Predicted price of {stock_id} is greater than latest price. We will trade this")
                    logging.info(f"writing the stock {stock_id} into a csv")
                    with open(f'{current_date}-list.txt', 'a') as file:
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
                if latest_price < (0.1 * (week_high - week_low)) + week_low:
                    logging.info(f"{stock_id} is not in the lowest it has been all week. skipping to the next")
                if latest_price < predicted_price and latest_price < (0.1 * (week_high - week_low)) + week_low:
                    logging.info(f"Predicted price of {stock_id} is greater than latest price. We will trade this")
                    logging.info(f"writing the stock {stock_id} into a csv")
                    with open(f'{current_date}-list.txt', 'a') as file:
                        file.write(f"{stock_id},")
            time.sleep(2)
    except Exception as e:
        logging.error(f"Tradinng bot generator failed: {str(e)}")
        return False
       

if __name__ == '__main__':  
    main()
