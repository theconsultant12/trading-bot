import robin_stocks.robinhood as rh
import sys
from multiprocessing import Pool
from datetime import datetime, timedelta
import time
import logging
import os
import argparse
import boto3
from predict_stock import run_lstm
from predict_stock_granular import run_lstm_granular
import pandas as pd
import atexit
import signal
import json
from decimal import Decimal


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

def canWeTrade(minimumBalance, maximumBalance) -> bool:
    """ here we check how much is available in the trading account and we start trading if we are less than 1100 and higher than 500"""
    trade = False
    global DAYCOUNT 
    try:
        withdrawable = float(rh.profiles.load_account_profile().get('portfolio_cash'))
        DAYCOUNT += 1
        if withdrawable > minimumBalance and withdrawable < maximumBalance:
            trade = True
            logging.info(f"your withdrawable balance is: {withdrawable}")
        else:
            trade = False   
            logging.info(f"we can no longer trade. your balance is either greate than {minimumBalance} or higher than the {maximumBalance} \n your spending balance is {withdrawable}")
    except Exception as e:
        logging.error(f"Error in canWeTrade: {str(e)}")
        
    return trade




def getAllTrades(group) -> list:
    """Here we get the stocks that exist under the category tag
    ‘biopharmaceutical’, ‘upcoming-earnings’, ‘most-popular-under-25’, ‘technology’"""
    global DAYCOUNT 
    count = 0
    min_max_values = {}
    stockArray = []
    stockList = []
    logging.info("getting all top moving trades in the past 40 seconds")

    try:
        while count < 10:
            response = rh.markets.get_all_stocks_from_market_tag(group)
            DAYCOUNT += 1
            for stock in response[:500]:
                if float(stock.get("ask_price")) < 200:
                    stockArray.append({stock.get("symbol"): stock.get("ask_price")})

            for stock in stockArray:
                for key, value in stock.items():
                    value = float(value)
                    if key in min_max_values:
                        if value < min_max_values[key]['min']:
                            min_max_values[key]['min'] = value
                        if value > min_max_values[key]['max']:
                            min_max_values[key]['max'] = value
                    else:
                        min_max_values[key] = {'min': value, 'max': value}
            count += 1

        # Calculate the differences and store them in a list of tuples
        differences = [(stock, values['max'] - values['min']) for stock, values in min_max_values.items()]

        # Filter out stocks with no difference
        differences = [item for item in differences if item[1] != 0]

        # Sort the list by the differences in descending order
        differences.sort(key=lambda x: x[1], reverse=True)

        # Log the top 5 differences
        if differences:
            logging.info("Top 5 stocks with the highest differences:")
            for i in range(min(5, len(differences))):
                stock, difference = differences[i]
                logging.info(f'{stock} - Difference: {difference}')
                stockList.append(stock)
        else:
            logging.info('No differences found.')

        logging.info("Stock list generated successfully")
    except Exception as e:
        logging.error(f"Error in getAllTrades: {str(e)}")

    return stockList



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




def monitorBuy(stock, dry, user_id) -> int:
    """this looks at a stock and monitors till it is at the lowest. we get the average for 10 seconds then wait till the cost is low then buy returns a float"""
    prices = []
    global DAYCOUNT 
    try:

        average = getWeightedAverage(stock)
        # we are trying to spend a reasonable amount per stock buy
        logging.info(average)
        quantity = int(500/average)
        count = 0
        if dry:
            costBuy = rh.stocks.get_latest_price(stock)[0]
            record_transaction(user_id, stock, 'buy', costBuy * quantity)
            logging.info(f"{costBuy}stock bought at {costBuy}  without checking")
        else:
            buyprice = rh.orders.order_buy_market(stock, quantity)  
            record_transaction(user_id, stock, 'buy', buyprice * quantity)
            logging.info(f"{buyprice.get('quantity')}stock bought at {buyprice.get('price')}  after checking {count} times")
        time.sleep(10)
        
        count = 0
        logging.info(f"waiting for price to rise current price is {rh.stocks.get_latest_price(stock)[0]} average is {average} buy price is {costBuy if dry else buyprice}")
        while float(rh.stocks.get_latest_price(stock)[0]) < average + (average * 0.0012):
            count += 1
            DAYCOUNT += 1
            time.sleep(50)
            if count%49 == 0:
                time.sleep(60)
        # sellprice = rh.orders.order_sell_market(stock, quantity) 
        if dry:
            costSell = rh.stocks.get_latest_price(stock)[0]
            logging.info(f"stock sold at {costSell} after checking {count} times")
            record_transaction(user_id, stock, 'sell', costSell * quantity)
            return float(costSell) - float(costBuy)
        else: 
            sellprice = rh.orders.order(symbol=stock, quantity=quantity, side='sell')
            record_transaction(user_id, stock, 'sell', sellprice * quantity)
            logging.info(f"stock sold at {sellprice} after checking {count} times") 
       
        diff = (sellprice * quantity) - (buyprice * quantity)
        logging.info(f'we made {diff} on this sale')
    except Exception as e:
        logging.error(f"Error in monitorBuy: {str(e)}")
        diff = 0
    return diff


# def monitorBuyCrypto(crypto, dry, user_id) -> int:
#     """this looks at a stock and monitors till it is at the lowest. we get the average for 10 seconds then wait till the cost is low then buy returns a float"""
#     prices = []
#     global DAYCOUNT 
#     try:

#         average = getWeightedAverage(crypto)
#         # we are trying to spend a reasonable amount per stock buy
#         logging.info(average)
#         quantity = int(500/average)
#         count = 0
#         logging.info(f"waiting for price to drop. average is {average} current price is {rh.stocks.get_latest_price(crypto)[0]}")
#         while float(rh.stocks.get_latest_price(crypto)[0]) > average - (average * 0.0012):
#             count += 1
#             DAYCOUNT += 1
#             time.sleep(2)
#             if count%49 == 0:
#                 time.sleep(60)
#         if dry:
#             costBuy = rh.stocks.get_latest_price(stock)[0]
#             record_transaction(user_id, stock, 'buy', costBuy * quantity)
#             logging.info(f"{costBuy}stock bought at {costBuy}  after checking {count} times")
#         else:
#             buyprice = rh.orders.order_buy_market(stock, quantity)  
#             record_transaction(user_id, stock, 'buy', buyprice * quantity)
#             logging.info(f"{buyprice.get('quantity')}stock bought at {buyprice.get('price')}  after checking {count} times")
#         time.sleep(10)
        
#         count = 0
#         logging.info(f"waiting for price to rise current price is {rh.stocks.get_latest_price(stock)[0]} average is {average}")
#         while float(rh.stocks.get_latest_price(stock)[0]) < average + (average * 0.0012):
#             count += 1
#             DAYCOUNT += 1
#             time.sleep(2)
#             if count%49 == 0:
#                 time.sleep(60)
#         # sellprice = rh.orders.order_sell_market(stock, quantity) 
#         if dry:
#             costSell = rh.stocks.get_latest_price(stock)[0]
#             logging.info(f"stock sold at {costSell} after checking {count} times")
#             record_transaction(user_id, stock, 'sell', costSell * quantity)
#             return float(costSell) - float(costBuy)
#         else: 
#             sellprice = rh.orders.order(symbol=stock, quantity=quantity, side='sell')
#             record_transaction(user_id, stock, 'sell', sellprice * quantity)
#             logging.info(f"stock sold at {sellprice} after checking {count} times") 
       
#         diff = (sellprice * quantity) - (buyprice * quantity)
#         logging.info(f'we made {diff} on this sale')
#     except Exception as e:
#         logging.error(f"Error in monitorBuy: {str(e)}")
#         diff = 0
#     return diff


#get total portfolio data

def getCurrentBalance():
    global DAYCOUNT 
    DAYCOUNT += 1
    try:
        return float(rh.profiles.load_portfolio_profile().get('withdrawable_amount'))
    except Exception as e:
        logging.error(f"Error in getCurrentBalance: {str(e)}")
        return 0.0

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


def main():
    try:
        # Update argument parser to include user_id
        parser = argparse.ArgumentParser(description='Trading bot configuration')
        parser.add_argument('-g', '--group', type=str, required=True, 
                          help='The group of stocks to trade (biopharmaceutical, upcoming-earnings, most-popular-under-25, technology)')
        parser.add_argument('-m', '--mode', type=str, required=True, 
                          help='Granularity of the LSTM machine learning predictive algorithm')
        parser.add_argument('-d', '--dry_run', type=str, required=True, 
                          help='Run the bot without using money')
        parser.add_argument('-u', '--user_id', type=str, required=True, 
                          help='Unique identifier for the user')

        args = parser.parse_args()

        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")

        logging.basicConfig(filename=f'{args.user_id}-{current_date}app.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
        
        pid_file_path = f'/tmp/{args.user_id}trading-bot-process.pid'
        create_pid_file(pid_file_path)
        logging.info(f"------------------------------------------------------------\n\nProcess started with PID: {os.getpid()}")
        atexit.register(cleanup)
        u = get_parameter_value('/robinhood/username')
        p = get_parameter_value('/robinhood/password')
        login()
        startBalance = getCurrentBalance()
        estimatedProfitorLoss = 0
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
  
        
        while canWeTrade(0, 2000) == True and startBalance - getCurrentBalance() < 50 and DAYCOUNT <= DAILYAPILIMIT:
            topTrade = getAllTrades(args.group)
            logging.info(f"these are the stocks we are trading{topTrade}")
            #run_lstm("NVDA")
            for stock_id in topTrade:
                if args.mode == "granular":
                    latest_price = float(rh.stocks.get_latest_price(stock_id)[0])
                    predicted_price = run_lstm_granular(stock_id, latest_price)
                    
                    if latest_price > predicted_price:
                        logging.info(f"Predicted price of {stock_id} is less than latest price. moving to the next stock")
                    data = rh.stocks.get_stock_historicals(stock_id,interval="10minute", span="week")
                    lowest_price = min(float(entry['low_price']) for entry in data)
                    highest_price = min(float(entry['high_price']) for entry in data)
                    if latest_price < (0.1 * (highest_price - lowest_price)) + lowest_price:
                        logging.info(f"{stock_id} is not in the lowest it has been all week. skipping to the next")
                    if latest_price < predicted_price and latest_price < (0.1 * (highest_price - lowest_price)) + lowest_price:
                        logging.info(f"Predicted price of {stock_id} is greater than latest price. We will trade this")
                        logging.info(f"trading {stock_id}")
                        diff = monitorBuy(stock_id, args.dry_run, args.user_id)
                        estimatedProfitorLoss += diff
                        time.sleep(10)
                else:
                    latest_price = float(rh.stocks.get_latest_price(stock_id)[0])
                    predicted_price = run_lstm(stock_id, latest_price)
                    
                    if latest_price > predicted_price:
                        logging.info(f"Predicted price of {stock_id} is less than latest price. moving to the next stock")
                    if latest_price < predicted_price:
                        logging.info(f"Predicted price of {stock_id} is greater than latest price. we will trade this")
                        logging.info(f"trading {stock_id}")
                        diff = monitorBuy(stock_id, args.dry_run, args.user_id)
                        estimatedProfitorLoss += diff
                        time.sleep(10)
            time.sleep(20)

        if DAYCOUNT >= DAILYAPILIMIT:
            reason = "daily api limit reached"  
            logging.info(reason)  
        if startBalance - getCurrentBalance() - startBalance == 500:
            
            reason = "we lost 50 dollars already during today's trade"  
            logging.info(reason)    
              
        endBalance = getCurrentBalance()
        
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