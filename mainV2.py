import sys
from multiprocessing import Pool
from datetime import datetime, timedelta
import time
import logging
import os
import argparse
import boto3
from generatelist import  get_parameter_value 
import pandas as pd
import atexit
import signal
import json
from decimal import Decimal
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


boto3.setup_default_session(region_name='us-east-1')


DAYCOUNT = 0
DAILYAPILIMIT = 19000


CARRIERS = {
    "att": "@mms.att.net",
    "tmobile": "@tmomail.net",
    "verizon": "@vtext.com",
    "sprint": "@messaging.sprintpcs.com"
}


current_date = datetime.now().strftime("%Y-%m-%d")


def create_pid_file(pid_file):
    pid = os.getpid()  # Get the current process ID
    with open(pid_file, 'w') as f:
        f.write(str(pid))  # Write PID to the file


def get_current_balance(alpaca_api_key, alpaca_secret_key, timeout = 10) -> float:
    url = (
        "https://paper-api.alpaca.markets/v2/account"
    )

    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": alpaca_api_key,
        "APCA-API-SECRET-KEY": alpaca_secret_key,
    }

    logging.info(f"Fetching current balance from Alpaca API")
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()          # raises on HTTP errors

        price = response.json().get("cash")
        logging.info(f"Successfully retrieved balance: ${float(price):.2f}")
        
        return float(price)  # Convert string to float before returning
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching balance from Alpaca API: {str(e)}")
        raise
    except (ValueError, TypeError) as e:
        logging.error(f"Error parsing balance response: {str(e)}")
        raise



def canWeTrade(
    min_balance,
    max_balance,
    alpaca_api_key: str,
    alpaca_secret_key: str,
    timeout: int = 10
) -> bool:
    """
    Fetch the latest bar for each symbol from Alpaca and return a
    dict of {ticker: latest_close_price}.
    """
    logging.info(f"Checking if we can trade with balance limits: min=${min_balance}, max=${max_balance}")
    # Build query string (Alpaca accepts comma‑separated list)
    price = get_current_balance(alpaca_api_key=alpaca_api_key, alpaca_secret_key=alpaca_secret_key)
    # Extract the `"c"` (close) price for each ticker
    if min_balance < price and max_balance > price:
        trade = True
        logging.info(f"Trading allowed: Current balance ${price:.2f} is within limits")
    else:
        trade = False
        logging.info(f"Trading not allowed: Current balance ${price:.2f} is outside limits (min=${min_balance}, max=${max_balance})")

    return trade

from multiprocessing import shared_memory
import json

SHM_NAME = "alpaca_prices"  # same name you used in writer
PRICE_MEM_SIZE = 1024       # same size as allocated

def read_shared_prices():
    try:
        shm = shared_memory.SharedMemory(name=SHM_NAME)
        raw = bytes(shm.buf[:PRICE_MEM_SIZE]).decode(errors="ignore")
        data = json.loads(raw or "{}")
        print(json.dumps(data, indent=2))  # Pretty-print the result
        return data
    except FileNotFoundError:
        print("Shared memory not found. Is the writer process running?")
        return {}
    except json.JSONDecodeError:
        print("Failed to decode JSON from shared memory.")
        return {}


    read_shared_prices()



def monitorBuy(stocks, dry, user_id, alpaca_api_key, alpaca_secret_key) -> int:
    """this looks at a stock and monitors till it is at the lowest. we get the average for 10 seconds then wait till the cost is low then buy returns a float"""
    prices = []
    global DAYCOUNT 
    try:
        
       
        # we are trying to spend a reasonable amount per stock buy
        for stock in stocks:
            logging.info(f"current price of {stock} is {float(current_stock_total.get(stock, 0))}")
        
        quantity = 2

        results = {}

        

        if not check_transaction(stocks):

            def run_buy(stock):
                return stock, place_order(stock, quantity, "buy", alpaca_api_key, alpaca_secret_key, dry)

            with ThreadPoolExecutor(max_workers=len(stocks)) as executor:
                futures = {executor.submit(run_buy, stock): stock for stock in stocks}
                for future in as_completed(futures):
                    stock, result = future.result()
                    results[stock] = result

            results

            total_cost = 0.0
            for stock, result in results.items():
                try:
                    price = float(result.get("filled_avg_price", 0))
                    qty = int(result.get("filled_qty", 0))
                    total_cost += price * qty
                except (TypeError, ValueError):
                    continue 

        
            record_transaction(user_id, stock, 'buy', total_cost)
            logging.info(f"{stocks} bought at {total_cost}  without checking")

        else:
            logging.info(f"we have stocks in hand that is trying to be sold by one of the bots")
        
        
        count = 0
        logging.info(f"waiting for {stocks} price to rise current bought price is {total_cost}")
        current_stock_total = read_shared_prices()



        while float(sum(float(current_stock_total.get(ticker, 0)) for ticker in stocks)) < total_cost + (total_cost * 0.0012):
            count += 1
        # sellprice = rh.orders.order_sell_market(stock, quantity) 
        def run_sell(stock):
            return stock, place_order(stock, quantity, "sell", alpaca_api_key, alpaca_secret_key, dry)

        with ThreadPoolExecutor(max_workers=len(stocks)) as executor:
            futures = {executor.submit(run_sell, stock): stock for stock in stocks}
            for future in as_completed(futures):
                stock, result = future.result()
                results[stock] = result

        results

        total_sale = 0.0
        for stock, result in results.items():
            try:
                price = float(result.get("filled_avg_price", 0))
                qty = int(result.get("filled_qty", 0))
                total_cost += price * qty
            except (TypeError, ValueError):
                continue 

      
        record_transaction(user_id, stock, 'buy', total_cost)
        logging.info(f"{stocks} bought at {total_cost}  without checking")
       
        diff = ( total_sale) - (total_cost)
        logging.info(f'we made {diff} on this sale')
    except Exception as e:
        logging.error(f"Error in monitorBuy: {str(e)}")
        diff = 0
    return diff


def place_order(stock, quantity, side, alpaca_api_key, alpaca_secret_key, dry_run=True):
    """
    Places a market order (buy or sell) on Alpaca.
    """
    url = (
        "https://paper-api.alpaca.markets/v2/orders"
        if dry_run else
        "https://api.alpaca.markets/v2/orders"
    )

    payload = {
        "type": "market",
        "time_in_force": "day",
        "symbol": stock,
        "qty": quantity,
        "side": side  # "buy" or "sell"
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "APCA-API-KEY-ID": alpaca_api_key,
        "APCA-API-SECRET-KEY": alpaca_secret_key
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        logging.info(f"{side.upper()} order for {stock} placed: {data}")
        return {
            "symbol": stock,
            "side": side,
            "filled_qty": data.get("filled_qty"),
            "filled_avg_price": data.get("filled_avg_price"),
            "status": data.get("status"),
            "raw": data
        }
    except Exception as e:
        logging.error(f"Failed to place {side} order for {stock}: {e}")
        return {
            "symbol": stock,
            "side": side,
            "error": str(e)
        }


def check_transaction(stocks):
    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')  # Replace with your table name
    
            
        logging.info("checking is stock has been bought today")
            # Create composite key with user_id and date
        response = table.scan(
        FilterExpression="begins_with(#k, :date)",
        ExpressionAttributeNames={
            "#k": "composite_key"  # Replace 'composite_key' with your actual attribute name
        },
        ExpressionAttributeValues={
            ":date": current_date
        
        }
        )
        
        # Track buys and sells
        bought = False
        
        # Process all transactions
        for item in response.get('Items', []):
            for stock in stocks:
                stock_returned = item['StockID']
                if stock_returned == stock:
                    bought = True
        return bought
         
    except Exception as e:
        logging.error(f"Failed to check if stock has been bought today: {str(e)}")
        return False



def record_transaction(user_id, stock, type, cost):
    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')  # Replace with your table name
    
            
            # Create composite key with user_id and date
        composite_key = f"{user_id}#{current_date}"
            
            # Create item for DynamoDB
        db_item = {
            'key': composite_key,  # Partition key: userId#date
            'UserId': user_id,
            'Date': current_date,
            'StockID': stock,
            'TransactionType': type,
            'Cost': cost,
            'Timestamp': datetime.now().isoformat()
        }
        
        # Put item in DynamoDB
        table.put_item(Item=db_item)
            
        logging.info(f"Data written to DynamoDB successfully for user {user_id}")
    except Exception as e:
        logging.error(f"Failed to write to DynamoDB: {str(e)}")


def closeDay():
    """Calculate end of day statistics and find unsold stocks"""
    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')
        
        # Get today's transactions
        response = table.scan(
        FilterExpression="begins_with(#k, :date)",
        ExpressionAttributeNames={
            "#k": "composite_key"  # Replace 'composite_key' with your actual attribute name
        },
        ExpressionAttributeValues={
            ":date": current_date
        }
        )
        
        # Track buys and sells
        stock_tracker = {}
        
        # Process all transactions
        for item in response.get('Items', []):
            stock = item['StockID']
            transaction_type = item['TransactionType']
            cost = float(item['Cost'])
            
            if stock not in stock_tracker:
                stock_tracker[stock] = {'buys': [], 'sells': []}
                
            if transaction_type == 'buy':
                stock_tracker[stock]['buys'].append(cost)
            elif transaction_type == 'sell':
                stock_tracker[stock]['sells'].append(cost)
        
        # Find unsold stocks and calculate statistics
        unsold_stocks = []
        total_profit = 0
        
        for stock, transactions in stock_tracker.items():
            buys_count = len(transactions['buys'])
            sells_count = len(transactions['sells'])
            
            if buys_count > sells_count:
                unsold_stocks.append({
                    'symbol': stock,
                    'unsold_quantity': buys_count - sells_count,
                    'buy_cost': sum(transactions['buys'][sells_count:])
                })
            
            # Calculate realized profit/loss
            for buy, sell in zip(transactions['buys'][:sells_count], transactions['sells']):
                total_profit += sell - buy
        
        # Log results
        logging.info(f"End of day summary for {current_date}:")
        logging.info(f"Total realized profit/loss: ${total_profit:.2f}")
        
        if unsold_stocks:
            logging.info("Unsold positions:")
            for position in unsold_stocks:
                logging.info(f"Stock: {position['symbol']}, "
                           f"Quantity: {position['unsold_quantity']}, "
                           f"Cost Basis: ${position['buy_cost']:.2f}")
        else:
            logging.info("No unsold positions")
            
        return unsold_stocks
        
    except Exception as e:
        logging.error(f"Error in closeDay: {str(e)}")
        return [], 0


def remove_pid_file(pid_file):
    if os.path.exists(pid_file):
        os.remove(pid_file)


def signal_handler(signum, frame):
    """Handle termination signals"""
    logging.info(f"Received signal {signum}. Performing cleanup...")
    cleanup()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)  # Handle kill
signal.signal(signal.SIGINT, signal_handler)   # Handle Ctrl+C



def cleanup():
    """Cleanup function to be called on exit"""
    try:
        closeDay()
        logging.info("Cleanup completed successfully")
    except Exception as e:
        logging.error(f"Error during cleanup: {str(e)}")

# Register cleanup functions


def read_stocks_to_trade() -> list[str]:
    """
    Read the stocks to trade from the date-stocks-to-trade.csv file.
    Returns a list of stock symbols.
    """
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    try:
        file_path = f'{current_date}-stocks-to-trade.csv'
        with open(file_path, 'r') as file:
            content = file.read().strip()
            if content:
                # Split by comma and remove any empty strings
                stocks = [stock.strip() for stock in content.split(',') if stock.strip()]
                logging.info(f"Successfully read {len(stocks)} stocks from {file_path}")
                return stocks
            else:
                logging.warning(f"No stocks found in {file_path}")
                return []
    except FileNotFoundError:
        logging.error(f"File {file_path} not found")
        return []
    except Exception as e:
        logging.error(f"Error reading stocks from {file_path}: {str(e)}")
        return []


def main():
    try:
        # Update argument parser to include user_id
        parser = argparse.ArgumentParser(description='Trading bot configuration')
        parser.add_argument('-d', '--dry_run', action='store_true', default=True, help='Run the bot without using money')
        parser.add_argument('-u', '--user_id', type=str, required=False, 
                          help='Unique identifier for the user')

        args = parser.parse_args()

        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")

        logging.basicConfig(filename=f'logs/trading-bot-logs/{args.user_id}-{current_date}app.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
        
        pid_file_path = f'/tmp/{args.user_id}trading-bot-process.pid'
        create_pid_file(pid_file_path)
        logging.info(f"------------------------------------------------------------\n\nProcess started with PID: {os.getpid()}")
        atexit.register(cleanup)

        logging.info(f"getting alpaca api key")
        alpaca_api_key = get_parameter_value("/alpaca/key")
        logging.info(f"getting alpaca secret key")
        alpaca_secret_key = get_parameter_value("/alpaca/secret")
        
        startBalance = get_current_balance(alpaca_api_key=alpaca_api_key, alpaca_secret_key=alpaca_secret_key)
        estimatedProfitorLoss = 0
        
        # Read stocks to trade from file
        topTrade = read_stocks_to_trade()
        if not topTrade:
            logging.error("No stocks to trade found. Exiting.")
            return
        batch_size = 4 #len(topTrade)/3

        #####################################################
        ## TEST SUITE
        #####################################################
        # data = rh.stocks.get_stock_historicals("ORCL",interval="10minute", span="day")
        
    
   
       

        # exit()
        #####################################################
        ## TEST SUITE
        #####################################################
        #write sms post message
        # message = f"Hello Olusola good day. We are about to start trading for the day. the starting balance is {startBalance}"
  
        
        while canWeTrade(min_balance=0, max_balance=100000,alpaca_api_key=alpaca_api_key,alpaca_secret_key=alpaca_secret_key) == True and DAYCOUNT <= DAILYAPILIMIT:

            logging.info(f"These are the stocks we are trading{topTrade}")
            
            for i in range(0, len(topTrade), batch_size):
                stock_ids = topTrade[i:i+batch_size]
                logging.info(f"trading batch: {stock_ids}")
                diff = monitorBuy(
                    stock_ids,  # list of 4 tickers
                    args.dry_run,
                    args.user_id,
                    alpaca_api_key=alpaca_api_key,
                    alpaca_secret_key=alpaca_secret_key
                )
                estimatedProfitorLoss += diff
                time.sleep(10)
                
            time.sleep(20)

        if DAYCOUNT >= DAILYAPILIMIT:
            reason = "daily api limit reached"  
            logging.info(reason)  
        if startBalance - get_current_balance(alpaca_api_key=alpaca_api_key, alpaca_secret_key=alpaca_secret_key)- startBalance == 500:
            
            reason = "we lost 50 dollars already during today's trade"  
            logging.info(reason)    
              
        endBalance = get_current_balance(alpaca_api_key=alpaca_api_key, alpaca_secret_key=alpaca_secret_key)
        
        if endBalance > startBalance:
            word = "PROFIT"
        else:
            word = "LOSS"
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        logging.info(current_date)
        actualProfit = endBalance - startBalance
        
        time.sleep(30)
    except Exception as e:
        logging.error(f"Error in main: {str(e)}")


if __name__ == '__main__':  
    main()

