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
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import OrderStatus


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



def read_shared_prices(retries=3, delay=0.1):
    for attempt in range(retries):
        try:
            shm = shared_memory.SharedMemory(name=SHM_NAME)
            raw_bytes = bytes(shm.buf[:PRICE_MEM_SIZE])
            raw_str = raw_bytes.decode(errors="ignore")

            # Trim at the last closing brace to try to make the JSON valid
            last_brace = raw_str.rfind("}")
            if last_brace != -1:
                raw_str = raw_str[:last_brace + 1]

            data = json.loads(raw_str)
            values = (json.dumps(data, indent=2))
            return data

        except FileNotFoundError:
            print("Shared memory not found. Is the writer process running?")
            return {}

        except json.JSONDecodeError as e:
            print(f"[Attempt {attempt+1}] Failed to decode JSON: {e}")
            time.sleep(delay)

    print("Failed to decode JSON from shared memory after retries.")
    return {}

def wait_for_order_fills(stock_list: list[str], timeout: int = 360, interval: int = 5, order_side: str = "buy") -> dict:
    """
    Wait until all orders for the given stock symbols are either filled or failed.

    :param stock_list: List of stock symbols to check
    :param timeout: Total max seconds to wait
    :param interval: Seconds to wait between checks
    :return: Dict of {symbol: final Order object or None if unresolved}
    """
    alpaca_api_key = get_parameter_value("/alpaca/key")
    alpaca_secret_key = get_parameter_value("/alpaca/secret")

    trading_client = TradingClient(alpaca_api_key, alpaca_secret_key, paper=True)

    deadline = time.time() + timeout
    symbols_pending = set(stock_list)
    final_orders = {}
    if order_side == "buy":
        order_side = OrderSide.BUY
    elif order_side == "sell":
        order_side = OrderSide.SELL

    logging.info(f"Waiting for orders to be filled or resolved: {stock_list}")

    while time.time() < deadline and symbols_pending:
        try:
            # Get all open + recent orders
            request = GetOrdersRequest(status=None)  # gets all orders
            orders = trading_client.get_orders(filter=request)

            for order in orders:
                sym = order.symbol
                if sym in symbols_pending:
                    if order.status == OrderStatus.FILLED and order.side == order_side:
                        logging.info(f"{sym} order resolved: {order.status}")
                        final_orders[sym] = order.filled_avg_price * order.filled_qty
                        symbols_pending.discard(sym)
                    elif order.status == OrderStatus.CANCELED:
                        logging.info(f"{sym} order canceled: {order.status}")
                        symbols_pending.discard(sym)
                    elif order.status == OrderStatus.REJECTED:
                        logging.info(f"{sym} order rejected: {order.status}")
                        symbols_pending.discard(sym)
                    else:
                        logging.debug(f"{sym} still pending: {order.status}")

        except Exception as e:
            logging.error(f"Error checking orders: {str(e)}")

        if symbols_pending:
            time.sleep(interval)

    # Final pass to record any unresolved orders
    if symbols_pending:
        logging.warning(f"Timeout reached. These symbols did not resolve: {symbols_pending}")
        for sym in symbols_pending:
            final_orders[sym] = None

    return final_orders

def monitorBuy(stocks, dry, user_id, alpaca_api_key, alpaca_secret_key) -> int:
    """this looks at a stock and monitors till it is at the lowest. we get the average for 10 seconds then wait till the cost is low then buy returns a float"""
    prices = []
    global DAYCOUNT 
    try:
        
       
        # we are trying to spend a reasonable amount per stock buy
        current_stock_total = sum(Decimal(str(read_shared_prices().get(ticker, 0))) for ticker in stocks)
        if not current_stock_total:
            logging.info(f"no stocks in shared memory")
            return 0
        
        
        quantity = 2

        buy_results = {}
        sell_results = {}
        total_cost = 0.0
        total_sale = 0.0
        # sellprice = rh.orders.order_sell_market(stock, quantity) 
        def run_sell(stock):
            return stock, place_order(stock, quantity, "sell", alpaca_api_key, alpaca_secret_key, dry)

        def run_buy(stock):
            return stock, place_order(stock, quantity, "buy", alpaca_api_key, alpaca_secret_key, dry)

        if not check_transaction(stocks):

            

            with ThreadPoolExecutor(max_workers=len(stocks)) as executor:
                futures = {executor.submit(run_buy, stock): stock for stock in stocks}
                for future in as_completed(futures):
                    stock, buy_result = future.result()
                    buy_results[stock] = buy_result

            

            logging.info(f"{stocks} bought at {buy_results}  without checking")

        else:
            logging.info(f"we have stocks in hand that is trying to be sold by one of the bots")
        bought_stocks = wait_for_order_fills(stocks, order_side="buy")  
        for stock, price in bought_stocks.items():
            record_transaction(user_id, stock, 'buy', price)
            total_cost += price
        
        count = 0
        logging.info(f"waiting for {bought_stocks.keys()} price to rise current bought price is {total_cost}")
       

        while sum(Decimal(str(read_shared_prices().get(ticker, 0))) for ticker in bought_stocks.keys()) < Decimal(total_cost) * Decimal("1.0012"): 
            count += 1
            time.sleep(5)
            pass

        with ThreadPoolExecutor(max_workers=len(stocks)) as executor:
            futures = {executor.submit(run_sell, bought_stocks.keys()): stock for stock in bought_stocks.keys()}
            for future in as_completed(futures):
                stock, result = future.result()
                sell_results[stock] = result

        

        sold_stocks = wait_for_order_fills(bought_stocks.keys(), order_side="sell")

        
        for stock, price in sold_stocks.items():
            record_transaction(user_id, stock, 'sell', price)
            total_sale += price

        logging.info(f"{sold_stocks.keys()} sold at {total_sale}  after checking {count} times")
       
        diff = (total_sale) - (total_cost)
        logging.info(f'we made {diff} on this sale')
    except Exception as e:
        logging.error(f"Error in monitorBuy: {str(e)}")
        diff = 0
    return diff



def place_order(stock, quantity, side, alpaca_api_key, alpaca_secret_key, dry_run=True):
    """
    Places a market order (buy or sell) on Alpaca using the official Alpaca SDK.
    """
    try:
        # Initialize the trading client
        trading_client = TradingClient(alpaca_api_key, alpaca_secret_key, paper=dry_run)

        # Convert string side to OrderSide enum
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

        # Create market order request
        market_order_data = MarketOrderRequest(
            symbol=stock,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.DAY
        )

        # Submit the order
        order = trading_client.submit_order(order_data=market_order_data)

        logging.info(f"{side.upper()} order for {stock} placed: {order}")

        return {
            "symbol": stock,
            "side": side,
            "filled_qty": getattr(order, "filled_qty", None),
            "filled_avg_price": getattr(order, "filled_avg_price", None),
            "status": order.status,
            "raw": order.__dict__
        }

    except APIError as e:
        logging.error(f"APIError placing {side} order for {stock}: {e}")
        return {"symbol": stock, "side": side, "error": str(e)}

    except Exception as e:
        logging.error(f"Unexpected error placing {side} order for {stock}: {e}")
        return {"symbol": stock, "side": side, "error": str(e)}
    

def check_transaction(stocks):
    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')  # Replace with your table name

        # Get today's date string (e.g., "2025-07-21")
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")

        logging.info("Checking if any stock has been bought today")

        # Scan table for items whose composite_key starts with today's date
        response = table.scan(
            FilterExpression="begins_with(#k, :date)",
            ExpressionAttributeNames={"#k": "composite_key"},
            ExpressionAttributeValues={":date": current_date}
        )

        bought_stocks = {item.get("StockID") for item in response.get("Items", [])}
        for stock in stocks:
            if stock in bought_stocks:
                logging.info(f"{stock} was already bought today")
                return True

        return False

    except Exception as e:
        logging.error(f"Failed to check stock transaction: {str(e)}")
        return False



def record_transaction(user_id, stock, type, cost):
    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')  # Replace with your table name

        # Get current date string
        current_date = datetime.now().strftime("%Y-%m-%d")

        # Create composite key with user_id and date
        composite_key = f"{user_id}#{current_date}"

        # Convert float to Decimal (use str to preserve precision)
        cost_decimal = Decimal(str(cost))

        # Create item for DynamoDB
        db_item = {
            'key': composite_key,  # Partition key: userId#date
            'UserId': user_id,
            'Date': current_date,
            'StockID': stock,
            'TransactionType': type,
            'Cost': cost_decimal,
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
    Reads stocks to trade from {current_date}-stocks-to-trade.csv, removes already traded ones,
    and appends newly picked stocks to traded.csv to prevent other bots from trading them.
    
    Returns a list of stocks to trade that haven't been traded yet.
    """
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    trade_file = f"{current_date}-stocks-to-trade.csv"
    traded_file = f"{current_date}-traded.csv"

    try:
        # Read all available stocks
        with open(trade_file, 'r') as file:
            content = file.read().strip()
            if not content:
                logging.warning(f"No stocks found in {trade_file}")
                return []

            all_stocks = [s.strip() for s in content.split(',') if s.strip()]
            logging.info(f"Read {len(all_stocks)} stocks from {trade_file}")
    except FileNotFoundError:
        logging.error(f"File {trade_file} not found")
        return []
    except Exception as e:
        logging.error(f"Error reading from {trade_file}: {str(e)}")
        return []

    # Read already traded stocks
    traded_stocks = set()
    if os.path.exists(traded_file):
        try:
            with open(traded_file, 'r') as tf:
                traded_stocks = set(tf.read().strip().split(','))
        except Exception as e:
            logging.error(f"Error reading from {traded_file}: {str(e)}")

    # Filter stocks that haven't been traded
    to_trade_now = [s for s in all_stocks if s not in traded_stocks]

    if not to_trade_now:
        logging.info("No new stocks left to trade")
        return []

    # Append the selected stocks to traded file
    try:
        with open(traded_file, 'a') as tf:
            if os.path.getsize(traded_file) > 0:
                tf.write(',')  # Add comma if file already has content
            tf.write(','.join(to_trade_now))
        logging.info(f"Logged {len(to_trade_now)} stocks to {traded_file}")
    except Exception as e:
        logging.error(f"Error writing to {traded_file}: {str(e)}")

    return to_trade_now


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

