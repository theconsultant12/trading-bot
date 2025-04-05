import robin_stocks.robinhood as rh
from predict_stock import run_lstm
from predict_stock_granular import run_lstm_granular
import pandas as pd
import logging
from datetime import datetime, timedelta
import time
import argparse
import boto3
import logging
import time
import requests
import os

now = datetime.now()
current_date = now.strftime("%Y-%m-%d")
logging.basicConfig(filename=f'logs/{current_date}-generator.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logging.info(f"-------------------------------------------------------------------------------------------------\n\n")


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
        print(f"Error occurred: {str(e)}")
        return None

finhub_key = get_parameter_value("finhub_api_key")
BASE_URL = "https://finnhub.io/api/v1"

CATEGORY_MAP = {
    "technology": [
        "AAPL", "MSFT", "GOOGL", "NVDA", "AMD", "INTC", "META", "CRM", "ADBE", "TSLA",
        "AVGO", "ORCL", "QCOM", "CSCO", "IBM", "SHOP", "PLTR", "SNOW", "UBER", "TWLO",
        "NET", "NOW", "TEAM", "SQ", "ROKU"
    ],
    "biopharmaceutical": [
        "AMGN", "GILD", "BIIB", "VRTX", "REGN", "MRNA", "BNTX", "SAGE", "IONS", "ALNY",
        "NBIX", "BLUE", "ARNA", "ABBV", "PFE", "LLY", "AZN", "NVS", "JNJ", "SNY",
        "VRTX", "BMY", "ZNTL", "NKTR", "XLRN"
    ]
}

DAYCOUNT = 0



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
        response = ssm_client.get_parameter(Name=parameter_name)
        return response['Parameter']['Value']

    except ssm_client.exceptions.ParameterNotFound:
        print(f"Parameter '{parameter_name}' not found.")
        return None

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return None
    



def update_price_data(symbol: str, api_key: str, 
                      interval='minute', interval_multiplier=5,
                      lookback_days=3) -> pd.DataFrame:
    logging.debug(f"Entering update_price_data function with parameters: symbol={symbol}, api_key={api_key}, interval={interval}, interval_multiplier={interval_multiplier}, lookback_days={lookback_days}")
    """
    For a given symbol, read the existing CSV (if it exists), figure out the last date
    for which data is stored, and fetch only new data from the API. Merge, deduplicate,
    and save back to CSV.

    Returns a DataFrame with the updated data.
    """

    # Decide on the CSV file name for this symbol
    csv_filename = f"data/{symbol}_prices.csv"

    # We'll track the earliest date we need to fetch. 
    # If CSV exists, read it and find the latest date we already have.
    if os.path.exists(csv_filename):
        logging.info(f"checking  if {symbol} csv file exists")
        df_existing = pd.read_csv(csv_filename, parse_dates=["timestamp"])
        df_existing.sort_values("timestamp", inplace=True)

        last_date = df_existing["timestamp"].max().date()
        logging.info(f"Existing data found for {symbol}. Last date in CSV: {last_date}")

        # We'll fetch from the day after the last known date
        # so we don't double-download duplicates
        start_date = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')

        # If the last_date is already today or in the future, 
        # no need to re-fetch
        today_str = datetime.now().strftime('%Y-%m-%d')
        if start_date > today_str:
            logging.info(f"No new data to fetch for {symbol}. Returning existing DataFrame.")
            return df_existing

    else:
        # If no CSV exists, fetch 'lookback_days' from today by default
        logging.info(f"No existing data for {symbol}, fetching entire range.")
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        df_existing = pd.DataFrame()  # empty placeholder

    # We'll fetch up to "today"
    end_date = datetime.now().strftime('%Y-%m-%d')

    # Build the request URL to financialdatasets.ai (as in your code):
    url = (
        f'https://api.financialdatasets.ai/prices/'
        f'?ticker={symbol}'
        f'&interval={interval}'
        f'&interval_multiplier={interval_multiplier}'
        f'&start_date={start_date}'
        f'&end_date={end_date}'
    )

    headers = {
        "X-API-KEY": api_key
    }

    logging.info(f"Fetching new data for {symbol} from {start_date} to {end_date}")
    response = requests.get(url, headers=headers)
    #logging.info(response.json().get("prices"))
    
    prices = response.json().get('prices', [])

    df_new = pd.DataFrame(prices)

    # If no new data was returned, just return existing
    if df_new.empty:
        logging.warning(f"No new data returned for {symbol}.")
        return df_existing

    # Rename 'time' -> 'timestamp' so that df_new["timestamp"] doesn't fail
    df_new.rename(columns={'time': 'timestamp'}, inplace=True)

    # Convert the 'timestamp' column to a proper datetime
    df_new["timestamp"] = pd.to_datetime(df_new["timestamp"])

    # Sort by timestamp
    df_new.sort_values("timestamp", inplace=True)

    # Merge df_existing and df_new, drop duplicates
    df_updated = pd.concat([df_existing, df_new], ignore_index=True)
    df_updated.drop_duplicates(subset=['timestamp'], inplace=True)
    df_updated.sort_values('timestamp', inplace=True)

    # Write back to CSV
    df_updated.to_csv(csv_filename, index=False)
    logging.info(f"Updated CSV saved: {csv_filename}")

    return df_updated



def getAllTrades(group: str, finhub_key: str) -> list:
    stockList = []
    movers = []

    logging.info("Getting top movers over the last hour using Finnhub historical data")

    tickers = CATEGORY_MAP.get(group, [])
    if not tickers:
        logging.warning(f"No tickers found for category '{group}'")
        return []

    try:
        for symbol in tickers:
            # -- USE THE HELPER FUNCTION HERE --
            # This will read existing CSV (if present),
            # and only fetch new data from the last known timestamp
            df_prices = update_price_data(symbol, finhub_key)

            if df_prices.empty:
                logging.warning(f"No data returned or stored for symbol: {symbol}")
                continue

            # Start price = first row’s open, End price = last row’s close
            start_price = df_prices.iloc[0]['open']
            end_price   = df_prices.iloc[-1]['close']
            difference  = abs(end_price - start_price)

            logging.info(f"Symbol: {symbol}, "
                         f"Start Price: {start_price}, "
                         f"End Price: {end_price}, "
                         f"Difference: {difference}")

            if start_price < 200:
                movers.append((symbol, difference))

        # Sort by price movement (descending)
        movers = [m for m in movers if m[1] > 0]
        movers.sort(key=lambda x: x[1], reverse=True)

        logging.info("Top 5 movers (last hour):")
        for symbol, diff in movers[:5]:
            logging.info(f"{symbol} - Moved: {diff}")
            stockList.append(symbol)

        logging.info("Stock list generated successfully")

    except Exception as e:
        logging.error(f"Error in getAllTrades: {str(e)}")

    return stockList



def main():
    try:
        # Update argument parser to include user_id
        parser = argparse.ArgumentParser(description='Trading bot configuration')
        parser.add_argument('-g', '--group', type=str, required=True, 
                          help='The group of stocks to trade (biopharmaceutical, upcoming-earnings, most-popular-under-25, technology)')
        
       

        args = parser.parse_args()



        
        starthour = 9
        #login()

        # response = rh.markets.get_all_stocks_from_market_tag("technology")
        # print(response)
        logging.info(f"time now is {datetime.now()}")
        if datetime.now().hour > starthour:
            logging.info(f"time now is {datetime.now()} and past the market start time running this in dry run")
            sampleTrade = getAllTrades(args.group, finhub_key)
            logging.info(f"these are the stocks we are trading{sampleTrade}")
            #run_lstm("NVDA")
            for stock_id in sampleTrade:
                latest_price = float(rh.stocks.get_latest_price(stock_id)[0])
                predicted_price = run_lstm(stock_id, latest_price)
                
                if latest_price > predicted_price:
                    logging.info(f"Predicted price of {stock_id} is less than latest price. moving to the next stock")
                data = rh.stocks.get_stock_historicals(stock_id,interval="10minute", span="week")
                lowest_price = min(float(entry['low_price']) for entry in data)
                highest_price = min(float(entry['high_price']) for entry in data)
                if latest_price < (0.1 * (highest_price - lowest_price)) + lowest_price:
                    logging.info(f"{stock_id} is not in the lowest it has been all week. skipping to the next")
                if latest_price < predicted_price and latest_price < (0.1 * (highest_price - lowest_price)) + lowest_price:
                    logging.info(f"Predicted price of {stock_id} is greater than latest price. We will trade this")
                    logging.info(f"writing the stock {stock_id} into a csv")
                    with open(f'{current_date}-list.txt', 'a') as file:
                        file.write(f"{stock_id},")
            time.sleep(2)
        while datetime.now().hour < starthour:
            logging.info(f" time is {datetime.now()}")
            
            sampleTrade = getAllTrades(args.group, finhub_key)
            logging.info(f"these are the stocks we are trading{sampleTrade}")
            #run_lstm("NVDA")
            for stock_id in sampleTrade:
                latest_price = float(rh.stocks.get_latest_price(stock_id)[0])
                predicted_price = run_lstm(stock_id, latest_price)
                
                if latest_price > predicted_price:
                    logging.info(f"Predicted price of {stock_id} is less than latest price. moving to the next stock")
                data = rh.stocks.get_stock_historicals(stock_id,interval="10minute", span="week")
                lowest_price = min(float(entry['low_price']) for entry in data)
                highest_price = min(float(entry['high_price']) for entry in data)
                if latest_price < (0.1 * (highest_price - lowest_price)) + lowest_price:
                    logging.info(f"{stock_id} is not in the lowest it has been all week. skipping to the next")
                if latest_price < predicted_price and latest_price < (0.1 * (highest_price - lowest_price)) + lowest_price:
                    logging.info(f"Predicted price of {stock_id} is greater than latest price. We will trade this")
                    logging.info(f"writing the stock {stock_id} into a csv")
                    with open(f'{current_date}-list.txt', 'a') as file:
                        file.write(f"{stock_id},")
            time.sleep(2)
    except Exception as e:
        logging.error(f"Login failed: {str(e)}")
        return False
       

if __name__ == '__main__':  
    main()
