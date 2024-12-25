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
            
        print(f"Data written to DynamoDB successfully for user {user_id}")
    except Exception as e:
        print(f"Failed to write to DynamoDB: {str(e)}")


def get_today_reports(n):
    """
    Fetch yesterday's trading reports from DynamoDB for the specified number of users.
    Returns a formatted string summarizing the reports.
    """
    print(f"Fetching yesterday's trading reports for {n} users")

    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')

        # Get yesterday's date for filtering reports
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        all_reports = []
        user_list = [f"U{str(i).zfill(3)}" for i in range(1, n + 1)]

        for user in user_list:
            print(f"Fetching report for user: {user}")
            # Construct the composite key using the user ID and yesterday's date
            composite_key = f"{user}#{yesterday}"
            try:
                response = table.query(
                    KeyConditionExpression=Key('key').eq(composite_key)
                )

                if response.get('Items'):
                    print(f"Found {len(response['Items'])} records for user {user}")
                    for item in response['Items']:
                        # Convert Decimal to float for easier handling
                        for key, value in item.items():
                            if key == 'Cost':
                                if isinstance(value, str) and value.replace('.', '', 1).isdigit():
                                   item[key] = Decimal(value)
                        all_reports.append(item)
                else:
                    print(f"No records found for user {user}")

            except Exception as e:
                print(f"Error fetching data for user {user}: {e}")
        if all_reports:
            print(f"Successfully retrieved {len(all_reports)} total reports")
            summary = f"Found {len(all_reports)} reports for yesterday.\n"

            for user in user_list:
                
                buy = 0.0
                sell = 0.0
                for report in all_reports:
                    if report.get('UserId') == user:
                        if report.get('TransactionType') == "buy":
                            costPrice = report.get("Cost")
                            parts = costPrice.split('.')    
                            if len(parts) > 2:
                                value = f"{parts[0]}.{''.join(parts[1:])}"
                            buy = float(Decimal(value))
                            
                        elif report.get('TransactionType') == "sell":
                            costPrice = report.get("Cost")
                            parts = costPrice.split('.')    
                            if len(parts) > 2:
                                value = f"{parts[0]}.{''.join(parts[1:])}"
                            sell = float(Decimal(value))
    
                summary += f"User {user} spent {buy:.2f} on buys and earned {sell:.2f} from sells.\n"

            print(summary)
            return summary
        else:
            print("No trading reports found for any users yesterday.")
            return "No trading reports found."

    except Exception as e:
        error_msg = f"Error fetching reports: {e}"
        print(error_msg)
        return error_msg
    


if __name__ == '__main__':
    #record_transaction("test-user000", "NVDA", "buy", 200)
    record_transaction("test-user", "mmm", 'buy', 200)
