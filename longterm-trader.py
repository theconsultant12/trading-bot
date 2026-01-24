# this is a long term trader. 
# Out of the tickers added to it, it monitors them and buys at a below 50 percent of the average then sells when it adds 6 percent (detects trend in the others).  
# controller already  exists 
# We will test rh api then move to alpaca
# get the tickers from the csv file
#  monitor for buy
#  monitor for sell 
# Tracker to store tickers we have. 
# Tracker to store price of buy and price of sell of each ticker. monitor progress of each ticker. 

def get_tickers():
    # get the tickers from the csv file
    with open('longterm-trader.csv', 'r') as file:
        reader = csv.reader(file)
        tickers = list(reader)
    return tickers

def monitor_for_buy():
    # monitor for buy
    pass

def monitor_for_sell():
    # monitor for sell
    pass

def main():
    tickers = get_tickers()
    monitor_for_buy()
    monitor_for_sell()