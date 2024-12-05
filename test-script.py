from multiprocessing import Pool
from datetime import datetime 
import time
import boto3
from datetime import date
current_dateTime = datetime.now()

now = datetime.now()

# Format the date
current_date = now.strftime("%Y-%m-%d")


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

print(checkTime())

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
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('bot-state-db')  # Replace with your table name

    # Get the current date in the desired format
    current_date = date.today().strftime('%Y-%m-%d')

    # Define filter for scanning items
    response = table.scan(
        FilterExpression="begins_with(#k, :date)",
        ExpressionAttributeNames={
            "#k": "composite_key"  # Replace 'composite_key' with your actual attribute name
        },
        ExpressionAttributeValues={
            ":date": current_date
        }
    )
    
    print(response)
