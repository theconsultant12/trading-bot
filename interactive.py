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
from mainV2 import  getCurrentBalance
import logging
import smtplib
from boto3.dynamodb.conditions import Key
from decimal import Decimal
import robin_stocks.robinhood as rh


now = datetime.now()
current_date = now.strftime("%Y-%m-%d")
logging.basicConfig(filename=f'{current_date}controller-logs.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

MODEL_PATH = os.path.join(os.path.abspath(os.getcwd()), "vosk-model-en-us-0.22")  
recognizer = vosk.KaldiRecognizer(vosk.Model(MODEL_PATH), 16000)

user_list = [
    'U001', 'U002', 'U003', 'U004', 'U005', 'U006', 'U007', 'U008', 'U009', 'U010',
    'U011', 'U012', 'U013', 'U014', 'U015', 'U016', 'U017', 'U018', 'U019', 'U020',
    'U021', 'U022', 'U023', 'U024', 'U025', 'U026', 'U027', 'U028', 'U029', 'U030',
    'U031', 'U032', 'U033', 'U034', 'U035', 'U036', 'U037', 'U038', 'U039', 'U040',
    'U041', 'U042', 'U043', 'U044', 'U045', 'U046', 'U047', 'U048', 'U049', 'U050',
    'U051', 'U052', 'U053', 'U054', 'U055', 'U056', 'U057', 'U058', 'U059', 'U060',
    'U061', 'U062', 'U063', 'U064', 'U065', 'U066', 'U067', 'U068', 'U069', 'U070',
    'U071', 'U072', 'U073', 'U074', 'U075', 'U076', 'U077', 'U078', 'U079', 'U080',
    'U081', 'U082', 'U083', 'U084', 'U085', 'U086', 'U087', 'U088', 'U089', 'U090',
    'U091', 'U092', 'U093', 'U094', 'U095', 'U096', 'U097', 'U098', 'U099', 'U100'
]


CARRIERS = {
    "att": "@mms.att.net",
    "tmobile": "@tmomail.net",
    "verizon": "@vtext.com",
    "sprint": "@messaging.sprintpcs.com"
}

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
def load_logs(dayArray):
    all_logs = []
    path = os.path.abspath(os.getcwd())
    logging.info(f"reading logs for {dayArray}")
    for day in dayArray:
        log_file = os.path.join(path, f'*{day}app.log') 
        
        if os.path.exists(log_file):
            with open(log_file, 'r') as file:
                logs = file.read()
                all_logs.append(logs)
        else:
            all_logs.append(f"Log file for {day} not found.")
    
    return "\n".join(all_logs) if all_logs else "No logs found."

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
        speak_with_polly(f"No logs found in the last {hours} hour(s) for any user.")
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

def load_logs_for_analysis(command):
    date_range = get_date_range(command)
    all_logs = ""

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




def start_trading_bot(mode, group, dryrun, user_id):
    try:
        # Get the current directory
        login_and_store_token()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Construct the path to mainV2.py
        bot_script_path = os.path.join(current_dir, 'mainV2.py')
        
        # Start the trading bot as a subprocess using python3
        process = subprocess.Popen(['python3', bot_script_path, '-m', mode, '-g', group, '-d', dryrun, '-u', user_id])
        speak_with_polly(f"{user_id}bot has been started successfully.")
        return "Trading bot started with PID: " + str(process.pid)
    except Exception as e:
        error_message = f"Failed to start bot. Error: {str(e)}"
        print(error_message)
        speak_with_polly(error_message)
        return error_message

def stop_trading_bot(n):
    try:
        for user in user_list[:int(n)]:
            pid_file_path = f'/tmp/{user}trading-bot-process.pid'
            
            # Check if the PID file exists
            if not os.path.exists(pid_file_path):
                speak_with_polly(f"{user} bot is not running.")
                return f"{user} bot is not running."
            
            # Read the PID from the file
            with open(pid_file_path, 'r') as f:
                pid = int(f.read().strip())
            
            # Try to terminate the process
            os.kill(pid, signal.SIGTERM)
            
            # Wait for a short time to allow the process to terminate
            time.sleep(2)
            
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
            
            return f"{user} bot stopped."
    except Exception as e:
        error_message = f"Failed to stop trading bot. Error: {str(e)}"
        speak_with_polly(error_message)
        return error_message




# Function to send the log data to GPT and get an explanation
def gpt_logs(keyword, log_text):
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",  # Updated to "gpt-4-turbo" since "gpt-4o-mini" might be incorrect or unavailable
        messages=[  # Messages should be a list of dicts
            {"role": "user", "content": f"{keyword} the following logs in simple terms:\n\n{log_text}. make the response concise"}
        ]
    )
    print(response.choices[0].message.content)
    return response.choices[0].message.content

    #return response.choices[0].message['content']


def currently_trading(n):
    count = 0
    for user in user_list[:int(n)]:
        pid_file_path = f'/tmp/{user}trading-bot-process.pid'
        if is_process_running(pid_file_path):
            count += 1
            
    if count:
        speak_with_polly(f"{count} trading bot is running.")
    else:
        speak_with_polly("no bots running")
    return count
          


def get_time_of_day():
    current_hour = datetime.now().hour  # Get the current hour (0-23)

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
    
    print("Listening for voice commands...")
    recognized_text = ""
    
    start_time = time.time()  # Track time to manage response delay
    
    while True:
        data = stream.read(2048, exception_on_overflow=False)
        if recognizer.AcceptWaveform(data):
            result = recognizer.Result()
            recognized_text = json.loads(result)["text"]
            if recognized_text:
                print(f"Recognized command: {recognized_text}")
                return recognized_text.lower()
       
            

def is_trading_time():
    current_time = datetime.now()
    target_time = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
    return current_time.hour == 9 and current_time.minute == 30

def auto_start_trading(n, dryrun="True"):
    logging.info(f"Starting auto-trading for {n} bots with dryrun={dryrun}")
    
    while True:
        if is_trading_time():
            mode = "granular"
            group = "technology"
            
            logging.info(f"Trading time detected. Starting {n} bots with mode={mode} and group={group}")
            speak_with_polly(f"It's 9 AM. Starting {n} trading bot with default settings.")
            
            for user in user_list[:int(n)]:
                logging.debug(f"Starting bot for user {user}")
                start_trading_bot(mode=mode, group=group, dryrun=dryrun, user_id=user)
            
            logging.info(f"All {n} bots started successfully")
            time.sleep(60)  # Wait for 60 seconds to avoid multiple starts
            
            message = f"Hello Olusola good day. Jarvis has started {n} bots. {getCurrentBalance()}"
            logging.debug(f"Sending start confirmation message: {message}")
            send_message("6185810303", "att", message)
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
                logging.info(f"Found {currently_running} active bots, checking their logs")
                logs = load_recent_logs(hours=0.17, n=currently_running)  # About 10 minutes
                
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
            print(f"Error in monitor thread: {str(e)}")
            time.sleep(600)  # Continue monitoring even if there's an error

def is_closing_time():
    current_time = datetime.now()
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
                
                message = f"Hello Olusola, Jarvis has stopped {n} bots for the day. here is his report{get_today_reports(n)}"
                send_message("6185810303", "att", message)
                logging.info("Sent end-of-day notification message")
                
                time.sleep(60)  # Wait to avoid multiple stops
            except Exception as e:
                logging.error(f"Error during shutdown sequence: {str(e)}", exc_info=True)
        
        time.sleep(30)  # Check every 30 seconds

def get_today_reports(n):
    """
    Fetch today's trading reports from DynamoDB for specified number of users
    Returns a formatted string of the reports
    """
    logging.info(f"Fetching today's trading reports for {n} users")
    
    try:
        # Initialize DynamoDB client
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('bot-state-db')
        today = datetime.now().strftime('%Y-%m-%d')
        logging.info(f"Querying DynamoDB for date: {today}")
        
        all_reports = []
        for user in user_list[:int(n)]:
            logging.info(f"Fetching report for user: {user}")
            response = table.query(
                KeyConditionExpression=Key('user_id').eq(user) & Key('date').eq(today)
            )
            
            if response['Items']:
                logging.info(f"Found {len(response['Items'])} records for user {user}")
                for item in response['Items']:
                    for key, value in item.items():
                        if isinstance(value, Decimal):
                            item[key] = float(value)
                    all_reports.append(item)
            else:
                logging.warning(f"No records found for user {user}")
        
        if all_reports:
            logging.info(f"Successfully retrieved {len(all_reports)} total reports")
            summary = f"Found {len(all_reports)} reports for today. "
            for report in all_reports:
                summary += f"User {report['user_id']} "
                if 'profit_loss' in report:
                    summary += f"P&L: ${report['profit_loss']:.2f}. "
                if 'trades_count' in report:
                    summary += f"Trades: {report['trades_count']}. "
            
            speak_with_polly(summary)
            return all_reports
        else:
            logging.warning("No trading reports found for any users today")
            speak_with_polly("No trading reports found for today.")
            return None
            
    except Exception as e:
        error_msg = f"Error fetching reports: {str(e)}"
        logging.error(error_msg, exc_info=True)
        speak_with_polly(error_msg)
        return None

def login_and_store_token():
    """Login to Robinhood and store the auth token for bots to use"""
    logging.info("Starting Robinhood login process")
    
    try:
        username = get_parameter_value('/robinhood/username')
        password = get_parameter_value('/robinhood/password')
        
        logging.info("Retrieved credentials from parameter store")
        
        response = rh.authentication.login(
            username=username,
            password=password,
            expiresIn=3600*24,  # 24 hours
            scope='internal',
            by_sms=True,
            store_session=True,
            mfa_code=None
        )
        
        logging.info("Login attempt completed")
        
        if response and 'access_token' in response:
            # Store token and timestamp in SSM
            ssm_client = boto3.client('ssm')
            token_data = {
                'token': response['access_token'],
                'timestamp': datetime.now().isoformat(),
                'expires_in': 3600*24
            }
            
            logging.info("Storing authentication token in SSM")
            
            ssm_client.put_parameter(
                Name='/robinhood/auth_token',
                Value=json.dumps(token_data),
                Type='SecureString',
                Overwrite=True
            )
            
            logging.info("Successfully stored authentication token in SSM")
            speak_with_polly("Successfully logged in and stored authentication token")
            return True
            
    except Exception as e:
        logging.error(f"Login failed with error: {str(e)}", exc_info=True)
        speak_with_polly(f"Failed to login: {str(e)}")
        return False

def main():
    n = 1
   
    
    # Start auto-trading checker in a separate thread
    auto_start_thread = threading.Thread(target=auto_start_trading, args=(n,), daemon=True)
    auto_start_thread.start()
    
    # Add the trading hours monitor thread
    trading_hours_thread = threading.Thread(target=monitor_trading_hours, args=(n,), daemon=True)
    trading_hours_thread.start()

     # Start the error monitoring thread
    error_monitor_thread = threading.Thread(target=monitor_logs_for_errors, args=(n,), daemon=True)
    error_monitor_thread.start()
    
    adjectives = ["read", "explain", "summarize"]
    ##########################################################
    ## TEST SUITE
    ##########################################################

    for user in user_list[:int(n)]:
                logging.debug(f"Starting bot for user {user}")
                start_trading_bot(mode="granular", group="Pharmaceutical", dryrun="True", user_id=user)
            
    logging.info(f"All {n} bots started successfully")
    time.sleep(60)  # W
    ##########################################################
    # END TEST SUITE
    ##########################################################
    # while True:
    #     voice_command = recognize_voice()
    #     adjectives = ["read", "explain", "summarize"]
    #     if "jarvis" in voice_command:
    #         if currently_trading(n):
    #             speak_with_polly(f"Hey Sola, good {get_time_of_day()}. {n} bots are running. What can I do for you today?")
    #         else:
    #             speak_with_polly(f"Hey Sola, good {get_time_of_day()}. no bots are running now. do you need anything else")

    #         speak_with_polly("Here are the list of prompts: 'read logs', 'are we trading'")
    #         voice_command = recognize_voice()
    #         if any(adj in voice_command for adj in adjectives):
    #               all_logs = load_logs_for_analysis("today")
    #               analyze_logs("summarize", all_logs)

    #         elif any(adj in voice_command for adj in adjectives) and "yesterday" in voice_command:
    #               all_logs = load_logs_for_analysis("yesterday")
    #               analyze_logs("summarize", all_logs)

    #         elif any(adj in voice_command for adj in adjectives) and "week" in voice_command:
    #               all_logs = load_logs_for_analysis("week")
    #               analyze_logs("summarize", all_logs)
            
    #         elif "reports" in voice_command:
    #             get_today_reports(n)

    #         elif "trading" in voice_command:
    #               currently_running = currently_trading(n)
    #               if currently_running != 0:  
    #                 logs = load_recent_logs(5, currently_trading(n))
    #                 analyze_logs("is there an error here, if not give a 3 line summary", logs)
            
    #         elif "stop" in voice_command:
    #               stop_trading_bot(n)
    #         elif "exit" in voice_command:
    #             speak_with_polly("Exiting the program.")
    #             break
    #         elif "pass" in voice_command:
    #             speak_with_polly("Exiting the program.")
    #             pass

    #         elif "kill" in voice_command:
    #             try:
    #                 speak_with_polly("Opening a terminal to show the command to kill the trading bot")
    #                 command = "ps aux | grep '[p]ython.*main.py' | awk '{print $2}'"
    #                 speak_with_polly("To kill the trading bot, copy this command and paste it in your terminal:")
    #                 speak_with_polly(command)
    #                 speak_with_polly("Then use: kill -9 followed by the process ID shown")
    #             except Exception as e:
    #                 speak_with_polly(f"Error providing kill command: {str(e)}")

    #         elif "login" in voice_command:
    #             login_and_store_token()

            





if __name__ == "__main__":
    main()
