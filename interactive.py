import os
import boto3
from datetime import datetime, timedelta
from playsound import playsound
import vosk
import sys
import json
import pyaudio
import subprocess
import signal
import time
from openai import OpenAI
import threading
from mainV2 import  get_current_balance
import logging
import smtplib
from boto3.dynamodb.conditions import Key
from decimal import Decimal
import robin_stocks.robinhood as rh
import pytz  # Add this import at the top
import asyncio
import websockets
from typing import Set, List, Dict, Tuple
from multiprocessing import shared_memory
import requests



now = datetime.now()
current_date = now.strftime("%Y-%m-%d")
logging.basicConfig(filename=f'logs/interactive-logs/{current_date}controller-logs.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

MODEL_PATH = os.path.join(os.path.abspath(os.getcwd()), "vosk-model-en-us-0.22")  
recognizer = vosk.KaldiRecognizer(vosk.Model(MODEL_PATH), 16000)

user_list = [f"U{str(i).zfill(3)}" for i in range(1, 101)]



def send_message(message):
    webhook_url = "https://discord.com/api/webhooks/1429499429500616819/QGTkav9VrxgLx6d6068fx0PbRtBUmm1xGFZ8jaDZPAY5hX6o1l7m7tq_gwC-cHU8QCRt"
    payload = {"content": f"📊 {message}"}
    requests.post(webhook_url, json=payload)
    

def is_process_running(pid_file):
    try:
        # Read the PID from the file
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())

        # Check if the process with the given PID is running
        os.kill(pid, 0)  # This sends signal 0 to check if the process exists
        return True  # Process is running
    except (OSError, FileNotFoundError, ValueError):
        # Process is not running or PID file doesn't exist
        return False



def get_parameter_value(parameter_name):
    """
    Retrieves the value of a parameter from AWS SSM Parameter Store.
    
    Args:
        parameter_name (str): The name of the parameter to retrieve.
    
    Returns:
        str: The value of the parameter, or None if not found or an error occurs.
    """
    ssm_client = boto3.client('ssm')
    logging.debug(f"Attempting to retrieve parameter: {parameter_name}")

    try:
        response = ssm_client.get_parameter(Name=parameter_name)
        value = response['Parameter']['Value']
        logging.info(f"Successfully retrieved parameter '{parameter_name}'")
        return value
    except ssm_client.exceptions.ParameterNotFound:
        logging.warning(f"Parameter '{parameter_name}' not found.")
        return None
    except Exception as e:
        logging.error(f"Error occurred while retrieving parameter '{parameter_name}': {str(e)}", exc_info=True)
        return None

openai = OpenAI(api_key=get_parameter_value('/openai/api-key'))
# Set your OpenAI API key


# Read the logs from a file
def load_logs(day):
    all_logs = []
    path = os.path.abspath(os.getcwd())
    logging.info(f"reading logs for {day}")
    import glob

    """
    Loads and combines all log files from a specific date.
    
    Args:
        directory (str): The path to the directory containing the log files.
        date (str): The date to filter logs by in the format 'YYYYMMDD'.
        
    Returns:
        str: The combined content of all logs from the specified date.
    """
    log_files_pattern = os.path.join(path, f"*{day}app.log")
    log_files = glob.glob(log_files_pattern)
    
    combined_logs = []
    
    for log_file in log_files:
        with open(log_file, 'r') as file:
            combined_logs.append(file.read())
    
    return "\n".join(combined_logs)
    

def load_recent_logs(hours=1, n=3):
    path = os.path.abspath(os.getcwd())
    logging.info(f"reading recent logs for the past {hours} on {n} bots")
    current_time = datetime.now()
    time_threshold = current_time - timedelta(hours=hours) 
    all_user_logs = []
    for user in user_list[:int(n)]:
        # Get today's date for the log file name
        today = current_time.strftime('%Y-%m-%d')
        log_file = os.path.join(path, f'*{user}*{today}app.log')
        
        if os.path.exists(log_file):
            with open(log_file, 'r') as file:
                logs = file.readlines()
            logging.info("logs loaded successfully")
            # Filter logs from the specified time period
            recent_logs = []
            for log in logs:
                try:
                    log_time = datetime.strptime(log.split()[0] + ' ' + log.split()[1], '%Y-%m-%d %H:%M:%S,%f')
                    if log_time >= time_threshold:
                        recent_logs.append(f"[{user}] {log.strip()}")
                except (ValueError, IndexError):
                    continue
            
            if recent_logs:
                all_user_logs.extend(recent_logs)
    
    if all_user_logs:
        return "\n".join(all_user_logs)
    else:
        logging.debug(f"No logs found in the last {hours} hour(s) for any user.")
        return None


def get_date_range(command):
    """
    Converts voice commands into a list of dates for log analysis.
    
    Args:
        command (str): Voice command containing time reference ('today', 'yesterday', or 'week')
    
    Returns:
        list: Array of date strings in 'YYYY-MM-DD' format
    """
    dateArray = []   
    today = datetime.now()
    logging.debug(f"Received command: {command}")

    # Handle "yesterday" command
    if 'yesterday' in command:
        yesterday = today - timedelta(days=1)
        logging.info(f"Processing 'yesterday': {yesterday.strftime('%Y-%m-%d')}")
        
        # Check if yesterday was a weekend
        if yesterday.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
            last_weekday = today - timedelta(days=today.weekday() - 4)
            logging.info(f"Yesterday was a weekend. Last weekday was: {last_weekday.strftime('%Y-%m-%d')}")
            speak_with_polly(f"The last weekday was: {last_weekday.strftime('%Y-%m-%d')}") 
            dateArray.append(last_weekday.strftime('%Y-%m-%d'))
            return dateArray 
        else:   
            dateArray.append(yesterday.strftime('%Y-%m-%d'))
            logging.info(f"Appending yesterday's date: {yesterday.strftime('%Y-%m-%d')}")
            return dateArray
    
    # Handle "today" command
    elif 'today' in command:
        logging.info("Processing 'today' command")
        
        # Check if today is a weekend
        if today.weekday() >= 5:
            last_weekday = today - timedelta(days=today.weekday() - 4)
            logging.info(f"Today is a weekend. Last weekday was: {last_weekday.strftime('%Y-%m-%d')}")
            speak_with_polly(f"The last weekday was: {last_weekday.strftime('%Y-%m-%d')}")
            dateArray.append(last_weekday.strftime('%Y-%m-%d'))
            return dateArray 
        else:
            dateArray.append(today.strftime('%Y-%m-%d'))
            logging.info(f"Appending today's date: {today.strftime('%Y-%m-%d')}")
            return dateArray 
    
    # Handle "week" command
    elif 'week' in command:
        logging.info("Processing 'week' command")
        # Get next 7 days, but only include weekdays
        for i in range(7):
            day = today + timedelta(days=i)
            if day.weekday() < 5:  # Only add Monday (0) through Friday (4)
                dateArray.append(day.strftime('%Y-%m-%d'))
                logging.debug(f"Appending weekday: {day.strftime('%Y-%m-%d')}")
        return dateArray
    
    # Log if no valid command found
    logging.warning("No valid date command found in the input.")
    return dateArray

def load_logs_for_analysis(command='today'):
    date_range = get_date_range(command)
    all_logs = ""
    logging.info(f"{date_range} type {type(date_range)}")
    for date in date_range:
        logs = load_logs(date)
        if logs:
            all_logs += f"\nLogs for {date}:\n{logs}\n"
        else:
            all_logs += f"\nNo logs found for {date}\n"
    return all_logs

def analyze_logs(keyword, all_logs):
    logging.info("sending logs to gpt for analyses")

    if all_logs:
        analysis = gpt_logs(keyword, all_logs)
        speak_with_polly(f"Here's the {keyword} of the logs: {analysis}")
    else:
        speak_with_polly("No logs were found for the specified date range.")


def start_generate_list():
    try:
        # Get the current directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Construct the path to generatelist.py
        bot_script_path = os.path.join(current_dir, 'generatelist.py')
        
        
        process = subprocess.Popen(['python3', bot_script_path])
        speak_with_polly(f"stock list generator has been started successfully.")
        return "stock list generator started with PID: " + str(process.pid)
    except Exception as e:
        error_message = f"Failed to start stock list generator. Error: {str(e)}"
        logging.info(error_message)
        speak_with_polly(error_message)
        return error_message


def start_trading_bot( dryrun, user_id):
    try:
        # Get the current directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Construct the path to mainV2.py
        bot_script_path = os.path.join(current_dir, 'mainV2.py')
        
        # Start the trading bot as a subprocess using python3
        if dryrun:
            process = subprocess.Popen(['python3', bot_script_path, '-d', '-u', user_id])
        else:
            process = subprocess.Popen(['python3', bot_script_path, '-d', '-u', user_id])
        speak_with_polly(f"{user_id}bot has been started successfully.")
    except Exception as e:
        error_message = f"Failed to start bot. Error: {str(e)}"
        logging.info(error_message)
        speak_with_polly(error_message)
        return error_message

def stop_trading_bot(n):
    try:
        for user in user_list[:int(n)]:
            pid_file_path = f'/tmp/{user}trading-bot-process.pid'
            
            # Check if the PID file exists
            if not os.path.exists(pid_file_path):
                speak_with_polly(f"{user} bot is not running.")
                logging.info(f"{user} bot is not running.")
            
            # Read the PID from the file
            with open(pid_file_path, 'r') as f:
                pid = int(f.read().strip())
            
            # Try to terminate the process
            os.kill(pid, signal.SIGTERM)
            
            # Wait for a short time to allow the process to terminate
            time.sleep(15)
            
            # Check if the process has terminated
            try:
                os.kill(pid, 0)
                # If we reach here, the process is still running
                os.kill(pid, signal.SIGKILL)
                speak_with_polly(f"{user} bot was forcefully terminated.")
            except OSError:
                # Process has terminated
                speak_with_polly(f"{user} bot has been stopped successfully.")
            
            # Remove the PID file
            os.remove(pid_file_path)
            
        return f"{n} bot stopped."
    except Exception as e:
        error_message = f"Failed to stop trading bot. Error: {str(e)}"
        speak_with_polly(error_message)
        return error_message


def stop_generate_list():
    try:
        logging.info("stopping stock list generator")
        pid_file_path = f'/tmp/generatelist-process.pid'
        
        if not os.path.exists(pid_file_path):
            speak_with_polly(f"stock list generator is not running.")
            logging.info(f"stock list generator is not running.")
        
        with open(pid_file_path, 'r') as f:
            pid = int(f.read().strip())
        
        if not os.kill(pid, signal.SIGTERM):
        
            time.sleep(15)
            try:
                os.kill(pid, 0)
                # If we reach here, the process is still running
                os.kill(pid, signal.SIGKILL)
                speak_with_polly(f"stock list generator was forcefully terminated.")
            except OSError:
                # Process has terminated
                speak_with_polly(f"stock list generator was stopped successfully.")
            
        # Remove the PID file
        os.remove(pid_file_path)
        
        return f"stock list generator stopped."
    except Exception as e:
        error_message = f"Failed to stop stock list generator. Error: {str(e)}"
        speak_with_polly(error_message)
        return error_message


# Function to send the log data to GPT and get an explanation
def gpt_logs(keyword, log_text):
    logging.info(log_text)
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",  # Updated to "gpt-4-turbo" since "gpt-4o-mini" might be incorrect or unavailable
        messages=[  # Messages should be a list of dicts
            {"role": "user", "content": f"{keyword} the following logs in simple terms:\n\n{log_text}. make the response concise"}
        ]
    )
    logging.info(response.choices[0].message.content)
    return response.choices[0].message.content

    #return response.choices[0].message['content']


def currently_trading(n):
    count = 0
    for user in user_list[:int(n)]:
        pid_file_path = f'/tmp/{user}trading-bot-process.pid'
        if is_process_running(pid_file_path):
            count += 1
            
    if count:
       logging.info(f"{count} trading bot is running.")
    else:
        logging.info("no bots running")
    return count
          


def get_time_of_day():
    eastern = pytz.timezone('US/Eastern')  # Define the Eastern timezone
    current_hour = datetime.now(eastern).hour  # Get the current hour in Eastern Time

    if 5 <= current_hour < 12:
        return "morning"
    elif 12 <= current_hour < 18:
        return "afternoon"
    else:
        return "evening"





def speak_with_polly(text, voice_id="Joanna", output_format="mp3"):
    # Initialize a session using Amazon Polly
    polly = boto3.client('polly')

    # Send request to Amazon Polly
    response = polly.synthesize_speech(
        Text=text,
        OutputFormat=output_format,
        VoiceId=voice_id
    )

    # Save the audio stream returned by Amazon Polly to a file
    if "AudioStream" in response:
        with open("speech.mp3", "wb") as file:
            file.write(response["AudioStream"].read())

    # Play the audio file
    playsound("speech.mp3")

    # Clean up the audio file after playing
    os.remove("speech.mp3")


def recognize_voice():
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
    stream.start_stream()
    
    logging.info("Listening for voice commands...")
    recognized_text = ""
    
    start_time = time.time()  # Track time to manage response delay
    
    while True:
        data = stream.read(2048, exception_on_overflow=False)
        if recognizer.AcceptWaveform(data):
            result = recognizer.Result()
            recognized_text = json.loads(result)["text"]
            if recognized_text:
                logging.info(f"Recognized command: {recognized_text}")
                return recognized_text.lower()
       
            

def is_trading_time():
    eastern = pytz.timezone('US/Eastern')  # Define the Eastern timezone
    current_time = datetime.now(eastern)  # Get the current time in Eastern Time
    
    # Check if today is a weekday (Monday to Friday)
    if current_time.weekday() >= 5: 
        return False
    
    # Check if the current time is exactly 9:30 AM
    return current_time.hour == 9 and current_time.minute == 30 

def is_generate_list_time():
    eastern = pytz.timezone('US/Eastern')  # Define the Eastern timezone
    current_time = datetime.now(eastern)  # Get the current time in Eastern Time
    
    # Check if today is a weekday (Monday to Friday)
    if current_time.weekday() >= 5: 
        return False
    
    return current_time.hour == 00 and current_time.minute == 00 

def auto_start_trading(n, dryrun):
    logging.info(f"Starting auto-trading for {n} bots with dryrun={dryrun}")
    
    
    while True:
        if is_trading_time():
            
            logging.info(f"Trading time detected. Starting {n} bots")
            speak_with_polly(f"Starting {n} trading bot with default settings.")
            
            
            for user in user_list[:int(n)]:
                logging.debug(f"Starting bot for user {user}")
                start_trading_bot(dryrun=dryrun, user_id=user)
                time.sleep(180)
            
            logging.info(f"All {n} bots started successfully")
            time.sleep(20)  # Wait for 60 seconds to avoid multiple start
            subset = user_list[:int(n)]
            running = [u for u in subset if is_process_running(f"/tmp/{u}trading-bot-process.pid")]

            if running:
                message = (f"Jarvis status at {datetime.now():%Y-%m-%d %H:%M:%S}: "
                        f"{len(running)}/{len(subset)} bots running: {', '.join(running)}")
                logging.debug(f"Sending start confirmation message: {message}")
                send_message(message)
            else:
                logging.debug("No bots are running.")
            
            
        else:
            pass
        
        time.sleep(30)  # Check every 30 seconds

def auto_start_generate_list():
    logging.info(f"Starting auto-trading for stock list generator")
    
    
    while True:
        if is_generate_list_time():
            
            logging.info(f"Trading time detected. Starting stock list generator")
            speak_with_polly(f"Starting stock list generator")
            
            
            start_generate_list()
            
            logging.info(f"stock list generator started successfully")
            message = f"Jarvis has started stock list generator. {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            logging.debug(f"Sending start confirmation message: {message}")
            send_message(message)
        else:
            pass
        
        time.sleep(30)  # Check every 30 seconds

def monitor_logs_for_errors(n):
    logging.info(f"Starting log monitoring for {n} bots")
    while True:
        try:
            logging.debug("Checking currently running bots")
            currently_running = currently_trading(n)
            
            if currently_running > 0:
                logging.info(f"Found {currently_running} active bots, monitoring their logs for errors ")
                logs = load_recent_logs(hours=1, n=currently_running)  # About 10 minutes
                
                if logs:
                    if "error" in logs.lower():
                        logging.warning("Errors detected in recent logs, sending for analysis")
                        analysis = gpt_logs("analyze this error and suggest a solution", logs)
                        logging.info(f"GPT Analysis: {analysis}")
                        speak_with_polly(f"Error detected in logs. Analysis: {analysis}")
                    else:
                        logging.debug("No errors found in recent logs")
                else:
                    logging.debug("No logs found in the recent time window")
                    
            else:
                pass
                
            time.sleep(600)  # Wait 10 minutes before next check
            
        except Exception as e:
            logging.error(f"Error in monitor thread: {str(e)}", exc_info=True)
            logging.info(f"Error in monitor thread: {str(e)}")
            time.sleep(600)  # Continue monitoring even if there's an error

def is_closing_time():
    eastern = pytz.timezone('US/Eastern')  # Define the Eastern timezone
    current_time = datetime.now(eastern)  # Get the current time in Eastern Time
    if current_time.weekday() >= 5: 
        return False
    
    return current_time.hour == 15 and current_time.minute == 30

def monitor_trading_hours(n):
    logging.info(f"Starting trading hours monitor for {n} bots")
    
    while True:
        current_time = datetime.now()
        logging.debug(f"Checking trading hours at {current_time}")
        
        if is_closing_time():
            logging.info(f"Closing time detected ({current_time}). Initiating shutdown sequence for {n} bots")
            speak_with_polly(f"It's 3:30 PM. Stopping {n} trading bots.")
            
            try:
                stop_trading_bot(n)
                logging.info("Successfully stopped trading bots")
                
                stop_generate_list()
                message = f"Jarvis has stopped stock list generator and {n} trading bots. {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                send_message(message)
                logging.info("Sent end-of-day notification message")
                
                time.sleep(60)  # Wait to avoid multiple stops
            except Exception as e:
                logging.error(f"Error during shutdown sequence: {str(e)}", exc_info=True)
        
        time.sleep(30)  # Check every 30 seconds

def cleanup():
    logging.info("Cleaning up: stopping all trading bots and terminating threads.")
    # Stop all trading bots
    n = len(user_list)  # Assuming you want to stop all bots
    stop_trading_bot(n)
    
    # Optionally, you can add logic to join threads if needed
    # For example, if you have references to the threads, you can join them here
    # auto_start_thread.join()
    # trading_hours_thread.join()
    # error_monitor_thread.join()

    logging.info("Cleanup completed.")

def signal_handler(signum, frame):
    """Handle termination signals"""
    logging.info(f"Received signal {signum}. Performing cleanup...")
    cleanup()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)  # Handle kill
signal.signal(signal.SIGINT, signal_handler) 


def get_today_reports(n):
    """
    Fetch yesterday's trading reports from DynamoDB for the specified number of users.
    Returns a formatted string summarizing the reports.
    """
    logging.info(f"Fetching yesterday's trading reports for {n} users")

    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')

        # Get yesterday's date for filtering reports
        yesterday = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')

        all_reports = []
        user_list = [f"U{str(i).zfill(3)}" for i in range(1, n + 1)]

        for user in user_list:
            logging.info(f"Fetching report for user: {user}")
            # Construct the composite key using the user ID and yesterday's date
            composite_key = f"{user}#{yesterday}"
            try:
                response = table.query(
                    KeyConditionExpression=Key('key').eq(composite_key)
                )

                if response.get('Items'):
                    logging.info(f"Found {len(response['Items'])} records for user {user}")
                    for item in response['Items']:
                        # Convert Decimal to float for easier handling
                        for key, value in item.items():
                            if key == 'Cost':
                                if isinstance(value, str) and value.replace('.', '', 1).isdigit():
                                   item[key] = Decimal(value)
                        all_reports.append(item)
                else:
                    logging.warning(f"No records found for user {user}")

            except Exception as e:
                logging.error(f"Error fetching data for user {user}: {e}")
        if all_reports:
            logging.info(f"Successfully retrieved {len(all_reports)} total reports")
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

            logging.info(summary)
            return summary
        else:
            logging.warning("No trading reports found for any users yesterday.")
            return "No trading reports found."

    except Exception as e:
        error_msg = f"Error fetching reports: {e}"
        logging.info(error_msg)
        return error_msg
    

async def keep_stream_alive(version: str = "v2", feed: str = "iex"):
    api_key = get_parameter_value("/alpaca/key")
    secret_key = get_parameter_value("/alpaca/secret")
    while True:
        try:
            await start_alpaca_stream(api_key, secret_key,version="v2", feed="iex")
        except Exception as e:
            logging.error(f"WebSocket crashed: {e}")
            await asyncio.sleep(5)  # backoff


def read_tickers_from_file():
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(f"stocks-to-trade.csv", 'r') as f:
            content = f.read().strip()
            tickers = [s.strip().upper() for s in content.split(',') if s.strip()]
            return set(tickers)
    except Exception as e:
        logging.info(f"Error reading ticker file: {e}")
        return set()
    
def build_sub_msg(action: str, tickers: Set[str]) -> dict:
    return {
        "action": action,
        # "trades": list(tickers),
        "quotes": list(tickers),
        "bars": list(tickers)
    }

# ---- Monitor file for ticker changes every 10 minutes ----
async def monitor_ticker_file(websocket, current_tickers: Set[str]):
    while True:
        await asyncio.sleep(600)  # wait 10 minutes
        new_tickers = read_tickers_from_file()

        to_add = new_tickers - current_tickers
        to_remove = current_tickers - new_tickers

        if to_remove:
            unsub_msg = build_sub_msg("unsubscribe", to_remove)
            await websocket.send(json.dumps(unsub_msg))
            logging.info(f"[INFO] Unsubscribed from: {sorted(to_remove)}")

        if to_add:
            sub_msg = build_sub_msg("subscribe", to_add)
            await websocket.send(json.dumps(sub_msg))
            logging.info(f"[INFO] Subscribed to: {sorted(to_add)}")

        current_tickers.clear()
        current_tickers.update(new_tickers)


async def start_alpaca_stream(api_key: str, secret_key: str, version: str = "v2", feed: str = "iex"):
    logging.info(f"Connecting to Alpaca stream at wss://stream.data.alpaca.markets/{version}/{feed}")
    url = f"wss://stream.data.alpaca.markets/{version}/{feed}"
    logging.info(f"[INFO] Connecting to {url}...")

    PRICE_MEM_SIZE = 1024  # bytes
    SHM_NAME = "alpaca_prices"

    shm = shared_memory.SharedMemory(create=True, size=PRICE_MEM_SIZE, name=SHM_NAME)

    try:
        async with websockets.connect(url) as websocket:
            # Step 1: Authenticate
            await websocket.send(json.dumps({
                "action": "auth",
                "key": api_key,
                "secret": secret_key
            }))

            auth_response = await websocket.recv()
            logging.info("[INFO] Auth response:", auth_response)

            # Step 2: Initial ticker load
            current_tickers = read_tickers_from_file()
            if not current_tickers:
                logging.warning("[WARN] No tickers found on startup. Watching for future changes.")

            # Step 3: Initial subscribe
            if current_tickers:
                sub_msg = build_sub_msg("subscribe", current_tickers)
                await websocket.send(json.dumps(sub_msg))
                logging.info(f"[INFO] Subscribed to: {sorted(current_tickers)}")

            # Step 4: Start ticker file monitor
            asyncio.create_task(monitor_ticker_file(websocket, current_tickers))

            while True:
                try:
                    msg = await websocket.recv()
                    data = json.loads(msg)
                    
                    for d in data:
                        if d.get("T") == "b":  # Bar message
                            symbol = d["S"]
                            price = d["c"]

                            # Read current state from shared memory
                            try:
                                raw_data = bytes(shm.buf[:]).decode(errors="ignore").strip('\x00')
                                current = json.loads(raw_data or "{}")
                            except json.JSONDecodeError:
                                logging.warning(f"Failed to decode JSON from shared memory. Raw data: {raw_data}")
                                current = {}

                            # Update with new price
                            current[symbol] = price

                            # Serialize and write back to shared memory
                            encoded = json.dumps(current).encode()

                            # Zero out the buffer before writing
                            shm.buf[:len(shm.buf)] = b'\x00' * len(shm.buf)

                            # Write only up to the length of the encoded JSON
                            shm.buf[:len(encoded)] = encoded

                except json.JSONDecodeError:
                    logging.warning("Received non-JSON message from websocket.")
                except Exception as e:
                    logging.error(f"Unexpected error in websocket loop: {e}")
                    await asyncio.sleep(1)  # Optional: avoid tight crash loop

    except Exception as e:
        logging.error(f"Stream error: {e}")


def run_stream():
    started = False
    eastern = pytz.timezone('US/Eastern')

    while True:
    
        now = datetime.now(eastern)

        # Run only Monday to Friday
        if now.weekday() < 5:
            # Wait for exactly 9:28 AM
            if now.hour == 10 and now.minute == 28 and not started:
                logging.info("[INFO] Starting Alpaca WebSocket stream at 9:28 AM ET...")
                asyncio.run(keep_stream_alive(version="v2", feed="iex"))
                started = True

            # Reset the `started` flag after 9:29 AM
            if now.hour == 10 and now.minute > 29:
                started = False

        time.sleep(30) 


def main():
    n = 2
    dryrun =True
   
    
   
    ##########################################################
    ## TEST SUITE
    ##########################################################

  
    # logging.debug(f"Starting bot for user testUser")
    # start_trading_bot(mode="granular", group="biopharmaceutical", dryrun="True", user_id="testUser")
    # for user in user_list[int(n):2]:
                
    #     logging.debug(f"Starting bot for user {user}")
    #     start_trading_bot(mode="granular", group="technology", dryrun="True", user_id=user)
    #     time.sleep(30)
            
    # logging.info(f"All {n} bots started successfully")
    # time.sleep(60)  # W
    ##########################################################
    # END TEST SUITE
    ##########################################################
     # Start auto-trading checker in a separate thread
    
    auto_start_thread = threading.Thread(target=auto_start_trading, args=(n, dryrun), daemon=True)
    auto_start_thread.start()

    auto_start_generate_list_thread = threading.Thread(target=auto_start_generate_list, daemon=True)
    auto_start_generate_list_thread.start()

    auto_stream_thread = threading.Thread(target=run_stream, daemon=True)
    auto_stream_thread.start()
    
    # Add the trading hours monitor thread
    trading_hours_thread = threading.Thread(target=monitor_trading_hours, args=(n,), daemon=True)
    trading_hours_thread.start()

     # Start the error monitoring thread
    error_monitor_thread = threading.Thread(target=monitor_logs_for_errors, args=(n,), daemon=True)
    error_monitor_thread.start()

    
    
    adjectives = ["read", "explain", "summarize"]

    while True:
        voice_command = recognize_voice()
        adjectives = ["read", "explain", "summarize"]
        if "jarvis" in voice_command:
            if currently_trading(n):
                speak_with_polly(f"Hey Sola, good {get_time_of_day()}. {n} bots are running. What can I do for you today?")
            else:
                speak_with_polly(f"Hey Sola, good {get_time_of_day()}. no bots are running now. do you need anything else")

            speak_with_polly("Here are the list of prompts: 'read logs', 'are we trading'")
            voice_command = recognize_voice()
            if any(adj in voice_command for adj in adjectives):
                  all_logs = load_logs_for_analysis("today")
                  analyze_logs("summarize", all_logs)

            elif any(adj in voice_command for adj in adjectives) and "yesterday" in voice_command:
                  all_logs = load_logs_for_analysis("yesterday")
                  analyze_logs("summarize", all_logs)

            elif any(adj in voice_command for adj in adjectives) and "week" in voice_command:
                  all_logs = load_logs_for_analysis("week")
                  analyze_logs("summarize", all_logs)
            
            elif "report" in voice_command:
                get_today_reports(n)

            elif "trading" in voice_command:
                  currently_running = currently_trading(n)
                  if currently_running != 0:  
                    logs = load_recent_logs(5, currently_trading(n))
                    analyze_logs("is there an error here, if not give a 3 line summary", logs)
            
            elif "stop" in voice_command:
                  stop_trading_bot(n)
                  

            elif "exit" in voice_command:
                speak_with_polly("Exiting the program.")
                break
            elif "pass" in voice_command:
                speak_with_polly("Call me if you need anything.")
                pass


            elif "kill" in voice_command:
                try:
                    speak_with_polly("Opening a terminal to show the command to kill the trading bot")
                    command = "ps aux | grep '[p]ython.*main.py' | awk '{print $2}'"
                    speak_with_polly("To kill the trading bot, copy this command and paste it in your terminal:")
                    speak_with_polly(command)
                    speak_with_polly("Then use: kill -9 followed by the process ID shown")
                except Exception as e:
                    speak_with_polly(f"Error providing kill command: {str(e)}")

    #         

            





if __name__ == "__main__":
    main()
