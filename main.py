import robin_stocks.robinhood as rh
import time
from multiprocessing import Pool
import importlib.util
import sys
from multiprocessing import Pool
from datetime import datetime
import time
import logging
import smtplib
import os
import argparse
import csv
import boto3


DAYCOUNT = 0
DAILYAPILIMIT = 19000

now = datetime.now()
current_date = now.strftime("%Y-%m-%d")

logging.basicConfig(filename=f'{current_date}app.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
CARRIERS = {
    "att": "@mms.att.net",
    "tmobile": "@tmomail.net",
    "verizon": "@vtext.com",
    "sprint": "@messaging.sprintpcs.com"
}


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


def send_message(phone_number, carrier, message):
    try:
        recipient = phone_number + CARRIERS[carrier]
        #use aws sns
        logging.info(f"sending message to {phone_number}")
        
        u = get_parameter_value('/mail/username')
        p = get_parameter_value('/mail/password')
        auth = [u, p]
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()

        server.login(auth[0], auth[1])
        server.sendmail(auth[0], recipient, message)
    except Exception as e:
        logging.error(f"Failed to send message: {str(e)}")


def send_sns_message(topic_arn, message):
    try:
        # Initialize a session using the AWS SDK for Python (Boto3)
        session = boto3.Session(region_name='us-east-1')  # Specify the region here

        # Create an SNS client
        sns_client = session.client('sns')

        try:
            # Send a message to the specified SNS topic
            response = sns_client.publish(
                TopicArn=topic_arn,
                Message=message
            )

            # Print the MessageId of the published message
            logging.info(f"Message published with MessageId: {response['MessageId']}")
            return response['MessageId']

        except Exception as e:
            print(f"Error publishing message: {str(e)}")
            return None
    except Exception as e:
        logging.error(f"Failed to send SNS message: {str(e)}")


# Example usage:
topic_arn = 'arn:aws:sns:us-east-1:123456789012:MyTopic'  # Replace with your topic ARN
message = 'Hello from Boto3!'  


def login(time, username, password):
    """This function logs you into the robinhood. time is in hours"""
    global DAYCOUNT 
    try:
        response = rh.authentication.login(username=username, 
                                password=password, 
                                expiresIn=3600*time, 
                                scope='internal', 
                                by_sms=True, 
                                store_session=True, 
                                mfa_code=None)
        logging.info(f"login successfully.")
        DAYCOUNT += 1
        logging.info(f"signed in for {time} hours ")
    except Exception as e:
        logging.error(f"Failed to login: {str(e)}")


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


def oldgetAllTrades(group) -> dict:
    """Here we get the stocks that exist under the category tag
    ‘biopharmaceutical’
    upcoming-earnings
    most-popular-under-25
    technology"""
    # update max for every
    global DAYCOUNT 
    count = 0
    min_max_values = {}
    max_values = {}
    stockArray = []
    stockList = []
    logging.info("getting all top moving trades in the past 40 seconds")
    try:
        while count < 10:
            response = rh.markets.get_all_stocks_from_market_tag(group)
            DAYCOUNT += 1
            for stock in response[:500]:
                if float(stock.get("ask_price")) < 200:
                    stockArray.append({stock.get("symbol"):stock.get("ask_price")}) 
            # logging.info(f"stock retrieved {stockArray}")
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
            
        # Calculate the differences and percentage changes and store them in a list of tuples
        differences = [(stock, values['max'] - values['min']) for stock, values in min_max_values.items()]
        logging.info("analysis completed")
        # Filter out stocks with no difference
        differences = [item for item in differences if item[1] != 0]

        # Sort the list by the differences in descending order
        differences.sort(key=lambda x: x[1], reverse=True)

        # logging.info the top 5 differences
        if differences:
            logging.info("Top 5 stocks with the highest differences and their percentage changes:")
            for i in range(min(5, len(differences))):
                stock, difference, percentage_change = differences[i]
                logging.info(f'{stock} - Difference: {difference}, Percentage Change: {percentage_change:.2f}%')
                stockList.append(stock)
        else:
            logging.info('No differences found.')
        logging.info("stock list generated successfully")
    except Exception as e:
        logging.error(f"Error in getAllTrades: {str(e)}")
    return stockList

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

def checkTime():
    """look through the time and compare to 9:30ET to 3:30ET return true if the time is within this window"""
    tradeTime = False
    tradeDate = False
    now = datetime.now()
    startTrade = now.replace(hour=9, minute=30, second=0, microsecond=0)
    endTrade = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now > startTrade and now < endTrade:
        tradeTime = True
    if datetime.today().weekday() in range(6):
        tradeDate = True
    return tradeTime and tradeDate

def monitorBuy(stock) -> int:
    """this looks at a stock and monitors till it is at the lowest. we get the average for 10 seconds then wait till the cost is low then buy returns a float"""
    prices = []
    global DAYCOUNT 
    try:
        for i in range(10):
            response = rh.stocks.get_latest_price(stock)
            DAYCOUNT += 1
            
            prices.append(float(response[0]))
            
            time.sleep(2)
        average = sum(prices) / len(prices)
        # we are trying to spend a reasonable amount per stock buy
        logging.info(average)
        quantity = int(500/average)
        count = 0
        priceBefore = getCurrentBalance()
        while float(rh.stocks.get_latest_price(stock)[0]) > average - (average * 0.0012):
            if not checkTime():
                logging.info(f"It seems like we are not in a trading time we will wait for trading to start current stock is {stock}")
                time.sleep(3600)
            logging.info(f"waiting for price to drop. average is {average} current price is {rh.stocks.get_latest_price(stock)[0]}")
            count += 1
            DAYCOUNT += 1
            time.sleep(20)
            if count%49 == 0:
                time.sleep(10)
        buyprice = rh.orders.order_buy_market(stock, quantity)  
        time.sleep(10)
        logging.info(f"stock bought at {buyprice} after checking {count} times")
        count = 0
        while float(rh.stocks.get_latest_price(stock)[0]) < average + (average * 0.0012):
            if not checkTime():
                logging.info(f"It seems like we are not in a trading time we will wait for trading to start current stock is {stock}")
                time.sleep(3600)
            logging.info(f"waiting for price to rise current price is {rh.stocks.get_latest_price(stock)[0]} average is {average}")
            count += 1
            DAYCOUNT += 1
            time.sleep(2)
            if count%49 == 0:
                time.sleep(10)
        sellprice = rh.orders.order_sell_market(stock, quantity)  
        logging.info(f"stock sold at {sellprice} after checking {count} times") 
        priceAfter = getCurrentBalance()
        diff = priceAfter - priceBefore
        logging.info(f'we made {diff} on this sale')
    except Exception as e:
        logging.error(f"Error in monitorBuy: {str(e)}")
        diff = 0
    return diff


def getCurrentBalance():
    global DAYCOUNT 
    DAYCOUNT += 1
    try:
        return float(rh.profiles.load_portfolio_profile().get('withdrawable_amount'))
    except Exception as e:
        logging.error(f"Error in getCurrentBalance: {str(e)}")
        return 0.0


def append_items_to_csv(items, filename):
    try:
        with open(filename, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerows(items)  # Append the data
        logging.info(f"Data appended to {filename} successfully.")
    except Exception as e:
        logging.error(f"Failed to append items to CSV: {str(e)}")


def main():
    try:
        # Create the parser
        parser = argparse.ArgumentParser(description='Which of the sectors will you like to trade biopharmaceutical \nupcoming-earnings \nmost-popular-under-25 \ntechnology')

        # Add arguments
        parser.add_argument('-g', '--group', type=str, required=True, help='The group of stocks to trade')

        # Parse the arguments
        args = parser.parse_args()
        u = get_parameter_value('/robinhood/username')
        p = get_parameter_value('/robinhood/password')
        login(24, u, p)
        startBalance = getCurrentBalance()
        estimatedProfitorLoss = 0
        #####################################################
        ## TEST SUITE
        #####################################################
        # response = rh.markets.get_all_stocks_from_market_tag("technology")
        # stockArray = []
        # for stock in response[:500]:
        #     if float(stock.get("ask_price")) < 200:
        #         stockArray.append({stock.get("symbol"):stock.get("ask_price")}) 
        # print(stockArray)

        #####################################################
        ## TEST SUITE
        #####################################################
        #write sms post message
        message = f"Hello Olusola good morning. We are about to start trading for the day. the starting balance is {startBalance}"
        send_message("6185810303", "tmobile", message)
        
        while canWeTrade(1500, 4000) == True and startBalance - getCurrentBalance() < 50 and DAYCOUNT <= DAILYAPILIMIT:
            topTrade = getAllTrades(args.group)
            logging.info(f"these are the stocks we are trading{topTrade}")
            for item in topTrade:
                logging.info(f"trading {item}")
                diff = monitorBuy(item)
                estimatedProfitorLoss += diff
                time.sleep(10)
            time.sleep(20)

        if DAYCOUNT >= DAILYAPILIMIT:
            reason = "daily api limit reached"   
        if startBalance - getCurrentBalance() - startBalance == 50:
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
        message = (f"Hello we have come to the end of the trading day we made an estimated  {word} of {actualProfit} because {reason}. \n total api calls made are {DAYCOUNT}")
        items = [(current_date, startBalance, endBalance, actualProfit)]
        csv_file = "monthlyreport.csv"
        time.sleep(30)
        send_message("6185810303", "tmobile", message)
        append_items_to_csv(items, csv_file)
    except Exception as e:
        logging.error(f"Error in main: {str(e)}")


if __name__ == '__main__':  
    main()

