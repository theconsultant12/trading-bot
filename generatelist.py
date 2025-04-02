
import robin_stocks.robinhood as rh
from predict_stock import run_lstm
from predict_stock_granular import run_lstm_granular
import pandas as pd
import logging
from datetime import datetime
import time
import argparse
import boto3

import logging
import time
import requests


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

FINNHUB_API_KEY = get_parameter_value("finhub_api_key")
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
    



def getAllTrades(group) -> list:
    stockList = []
    movers = []

    logging.info("Getting top movers over the last hour using Finnhub historical data")

    tickers = CATEGORY_MAP.get(group, [])
    if not tickers:
        logging.warning(f"No tickers found for category '{group}'")
        return []

    # Calculate UNIX timestamps for the past hour
    end_time = int(time.time())
    start_time = end_time - 60 * 60  # 1 hour ago

    try:
        for symbol in tickers:
            url = f"{BASE_URL}/stock/candle"
            params = {
                "symbol": symbol,
                "resolution": "1",  # 1-minute candles
                "from": start_time,
                "to": end_time,
                "token": FINNHUB_API_KEY
            }

            res = requests.get(url, params=params)
            print(res)
            data = res.json()

            if data.get("s") != "ok" or not data.get("o"):
                continue

            start_price = data["o"][0]
            end_price = data["c"][-1]
            difference = abs(end_price - start_price)

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

        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")

        logging.basicConfig(filename=f'{current_date}app.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
        
        
        logging.info(f"------------------------------------------------------------\n\n")
        #login()
        
        while datetime.now().hour < 15:
            logging.info(f" time is {datetime.now()}")
            
            topTrade = getAllTrades(args.group)
            logging.info(f"these are the stocks we are trading{topTrade}")
            #run_lstm("NVDA")
            for stock_id in topTrade:
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
