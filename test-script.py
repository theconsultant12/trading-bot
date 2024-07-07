from multiprocessing import Pool
from datetime import datetime
import time
import robin_stocks.robinhood as rh

current_dateTime = datetime.now()

now = datetime.now()

# Format the date
current_date = now.strftime("%Y-%m-%d")
print(current_date)

withdrawable = float(rh.profiles.load_account_profile().get('withdrawable_amount'))
withdrawable = float(rh.profiles.load_portfolio_profile().get('withdrawable_amount'))
def f(x):
    return x*x

if __name__ == '__main__':
    # get the start time
    # st = time.time()
    # p = Pool(5)
    # print(p.map(f, [1, 2, 3, 4, 5, 6, 7, 8, 9]))
    
    # et = time.time()
    
    # elapsed_time = et - st
    
    
    # st = time.time()
    # for i in [1,2,3, 4, 5, 6, 7, 8, 9]:
    #     print(f(i))
    
    # et = time.time()
    
    # arrelapsed_time = et - st
    
    # print(f"time of thread = {elapsed_time} \ntime of for = {arrelapsed_time}")
    print(datetime.date)