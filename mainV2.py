import sys
import threading
from multiprocessing import Pool
from datetime import datetime, timedelta
import time
import logging
import os
import argparse
import boto3
from generatelist import get_parameter_value
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
_shm_lock = threading.Lock()  # guards shared memory reads


def read_shared_prices(retries=3, delay=0.1):
    for attempt in range(retries):
        try:
            with _shm_lock:
                shm = shared_memory.SharedMemory(name=SHM_NAME)
                raw_bytes = bytes(shm.buf[:PRICE_MEM_SIZE])
                shm.close()

            raw_str = raw_bytes.decode(errors="ignore")
            last_brace = raw_str.rfind("}")
            if last_brace != -1:
                raw_str = raw_str[:last_brace + 1]

            return json.loads(raw_str)

        except FileNotFoundError:
            logging.warning("Shared memory not found. Is the price stream running?")
            return {}

        except json.JSONDecodeError as e:
            logging.debug(f"[Attempt {attempt+1}] Failed to decode shared-memory JSON: {e}")
            time.sleep(delay)

    logging.error("Failed to decode shared-memory JSON after %d retries.", retries)
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

MAX_HOLD_SECONDS = 1800       # 30-minute max hold before force-sell
PROFIT_TARGET = Decimal("1.0012")   # 0.12% gain target
STOP_LOSS_FACTOR = Decimal("0.995") # 0.5% drop triggers stop-loss


def monitorBuy(stocks, dry, user_id, alpaca_api_key, alpaca_secret_key) -> float:
    """
    Buy a batch of stocks, then sell when the profit target is reached,
    a stop-loss is triggered, or MAX_HOLD_SECONDS elapses.
    Returns the realised P&L for this batch.
    """
    global DAYCOUNT
    diff = 0.0
    try:
        current_prices = read_shared_prices()
        if not any(current_prices.get(ticker) for ticker in stocks):
            logging.info("No prices in shared memory for %s — skipping batch", stocks)
            return 0

        quantity = 2

        buy_results: dict = {}
        sell_results: dict = {}
        total_cost = 0.0
        total_sale = 0.0

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
            logging.info("%s buy orders submitted: %s", stocks, buy_results)
        else:
            logging.info("One or more stocks in %s already traded today — skipping buys", stocks)

        bought_stocks = wait_for_order_fills(stocks, order_side="buy")
        for stock, price in bought_stocks.items():
            if price is not None:
                record_transaction(user_id, stock, 'buy', price)
                total_cost += float(price)

        if not total_cost:
            logging.warning("No fills confirmed for %s — nothing to sell", stocks)
            return 0

        logging.info("Holding %s — total cost $%.2f. Waiting for +%.2f%% gain.",
                     list(bought_stocks.keys()), total_cost,
                     float(PROFIT_TARGET - 1) * 100)

        # Monitor: sell on profit target, stop-loss, or timeout
        count = 0
        wait_start = time.time()
        while True:
            prices_now = read_shared_prices()
            # Compare current portfolio value (price × qty) against total cost
            current_value = sum(
                Decimal(str(prices_now.get(ticker, 0))) * Decimal(str(quantity))
                for ticker in bought_stocks
            )

            if current_value >= Decimal(str(total_cost)) * PROFIT_TARGET:
                logging.info("Profit target hit: current value $%.2f", float(current_value))
                break
            if current_value > 0 and current_value < Decimal(str(total_cost)) * STOP_LOSS_FACTOR:
                logging.warning("Stop-loss triggered: $%.2f < floor $%.2f",
                                float(current_value),
                                float(Decimal(str(total_cost)) * STOP_LOSS_FACTOR))
                break
            if time.time() - wait_start > MAX_HOLD_SECONDS:
                logging.warning("Max hold time (%ds) reached — forcing sell", MAX_HOLD_SECONDS)
                break

            count += 1
            time.sleep(5)

        # Place sell orders (one per stock)
        with ThreadPoolExecutor(max_workers=len(bought_stocks)) as executor:
            futures = {executor.submit(run_sell, stock): stock for stock in bought_stocks}
            for future in as_completed(futures):
                stock, result = future.result()
                sell_results[stock] = result

        sold_stocks = wait_for_order_fills(list(bought_stocks.keys()), order_side="sell")
        for stock, price in sold_stocks.items():
            if price is not None:
                record_transaction(user_id, stock, 'sell', price)
                total_sale += float(price)

        diff = total_sale - total_cost
        logging.info("%s sold after %d checks — cost $%.2f  sale $%.2f  P&L $%.4f",
                     list(sold_stocks.keys()), count, total_cost, total_sale, diff)

    except Exception as e:
        logging.error("Error in monitorBuy: %s", str(e), exc_info=True)
        diff = 0.0

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
        from boto3.dynamodb.conditions import Attr
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')
        current_date = datetime.now().strftime("%Y-%m-%d")

        logging.info("Checking if any stock in %s was already bought today", stocks)

        response = table.scan(
            FilterExpression=Attr("Date").eq(current_date)
        )

        bought_today = {item.get("StockID") for item in response.get("Items", [])}
        for stock in stocks:
            if stock in bought_today:
                logging.info("%s was already traded today — skipping batch", stock)
                return True

        return False

    except Exception as e:
        logging.error("Failed to check stock transaction: %s", str(e))
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
        
        from boto3.dynamodb.conditions import Attr
        # Get today's transactions using the Date attribute
        response = table.scan(
            FilterExpression=Attr("Date").eq(current_date)
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
    Reads stocks to trade from stocks-to-trade.csv, removes already traded ones,
    and appends newly picked stocks to traded.csv to prevent other bots from trading them.
    
    Returns a list of stocks to trade that haven't been traded yet.
    """
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    trade_file = f"stocks-to-trade.csv"
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
            logging.info("Daily API limit reached (%d calls)", DAILYAPILIMIT)

        endBalance = get_current_balance(alpaca_api_key=alpaca_api_key, alpaca_secret_key=alpaca_secret_key)
        daily_loss = startBalance - endBalance
        if daily_loss >= 500:
            logging.warning("Daily loss limit hit: lost $%.2f today", daily_loss)
        
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

