from multiprocessing import Pool
from datetime import datetime 
import time
import boto3
from datetime import date
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from datetime import timedelta

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


def get_today_reports(n):
    """
    Fetch yesterday's trading reports from DynamoDB for specified number of users.
    Returns a formatted string of the reports.
    """
    print(f"Fetching yesterday's trading reports for {n} users")
    
    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')
        
        # Get yesterday's date for filtering reports
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        all_reports = []
        user_list = [ "U001"]
        for user in user_list:
            print(f"Fetching report for user: {user}")
            # Construct the composite key using the user ID and yesterday's date
            composite_key = f"{user}#{yesterday}"
            response = table.query(
                KeyConditionExpression=Key('key').eq(composite_key)
            )
            
            if response['Items']:
                print(f"Found {len(response['Items'])} records for user {user}")
                for item in response['Items']:
                    # Convert Decimal to float for easier handling
                    for key, value in item.items():
                        if isinstance(value, Decimal):
                            item[key] = float(value)
                    all_reports.append(item)
            else:
                print(f"No records found for user {user}")
        
        if all_reports:
            print(f"Successfully retrieved {len(all_reports)} total reports")
            summary = f"Found {len(all_reports)} reports for today. "
            for report in all_reports:
                summary += f"User {report['user_id']} "
                if 'profit_loss' in report:
                    summary += f"P&L: ${report['profit_loss']:.2f}. "
                if 'trades_count' in report:
                    summary += f"Trades: {report['trades_count']}. "
            
          
            return all_reports
        else:
            print("No trading reports found for any users today")
  
            return None
            
    except Exception as e:
        error_msg = f"Error fetching reports: {str(e)}"
  
        return None

if __name__ == '__main__':
    # get the start time
    # st = time.time()
    # p = Pool(5)
    # print(p.map(f, [1, 2, 3, 4, 5, 6, 7, 8, 9]))
    
    # et = time.time()
    
    # elapsed_time = et - st
    
    
    # st = time.time()
    print(get_today_reports(1))
    # for i in [1,2,3, 4, 5, 6, 7, 8, 9]:
    #     print(f(i))
    
    # et = time.time()
    
    # arrelapsed_time = et - st
    
    # print(f"time of thread = {elapsed_time} \ntime of for = {arrelapsed_time}")

    