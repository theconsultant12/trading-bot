import robin_stocks.robinhood as rh
import time
from multiprocessing import Pool
import importlib.util
import sys
from multiprocessing import Pool
from datetime import datetime, timedelta
import time
import logging
import smtplib
import os
import argparse
import csv
import boto3
from predict_stock import run_lstm
from predict_stock_granular import run_lstm_granular
import pandas as pd
import atexit
import signal
import json
from decimal import Decimal
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor
from checker import record_transaction


boto3.setup_default_session(region_name='us-east-1')


DAYCOUNT = 0
DAILYAPILIMIT = 19000

def monitorSell(stock, buy):
    global DAYCOUNT
    DAYCOUNT += 1
    try:
        while float(rh.stocks.get_latest_price(stock)[0]) < buy - (buy * 0.0012):
            count += 1
            DAYCOUNT += 1
            time.sleep(50)
            if count%49 == 0:
                time.sleep(60)
        sell_price = rh.orders.order_sell_market(stock, quantity)
        logging.info(f"Selling {stock} at {sell_price} for a profit")
        quantity = int(500/sell_price)
        record_transaction(stock, 'sell', sell_price * quantity)
        logging.info(f"{quantity} shares of {stock} sold at {sell_price.get('price')} for a profit")

    except Exception as e:
        logging.error(f"Error in monitorSell: {str(e)}")
    