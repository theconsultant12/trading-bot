import openai
import pyttsx3
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

# Initialize the vosk recognizer with a model path
MODEL_PATH = "/Users/macbook/workspace/rob-test/vosk-model-en-us-0.22-lgraph"  # e.g., "vosk-model-small-en-us-0.15"
recognizer = vosk.KaldiRecognizer(vosk.Model(MODEL_PATH), 16000)


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


# Set your OpenAI API key
openai.api_key = get_parameter_value('/openai/api-key')


# Initialize the text-to-speech engine
engine = pyttsx3.init()


# Read the logs from a file
def load_logs(dayArray):
    all_logs = []
    path = os.path.abspath(os.getcwd())
    
    for day in dayArray:
        log_file = os.path.join(path, f'{day}app.log')
        
        if os.path.exists(log_file):
            with open(log_file, 'r') as file:
                logs = file.read()
                all_logs.append(logs)
        else:
            all_logs.append(f"Log file for {day} not found.")
    
    return "\n".join(all_logs) if all_logs else "No logs found."

def load_recent_logs(hours=1):
    path = os.path.abspath(os.getcwd())
    current_time = datetime.now()
    time_threshold = current_time - timedelta(hours=hours)
    
    # Get today's date for the log file name
    today = current_time.strftime('%Y-%m-%d')
    log_file = os.path.join(path, f'{today}app.log')
    
    if os.path.exists(log_file):
        with open(log_file, 'r') as file:
            logs = file.readlines()
        
        # Filter logs from the specified time period
        recent_logs = []
        for log in logs:
            try:
                log_time = datetime.strptime(log.split()[0] + ' ' + log.split()[1], '%Y-%m-%d %H:%M:%S,%f')
                if log_time >= time_threshold:
                    recent_logs.append(log.strip())
            except (ValueError, IndexError):
                # Skip lines that don't start with a timestamp
                continue
        
        return "\n".join(recent_logs) if recent_logs else f"No logs found in the last {hours} hour(s)."
    else:
        return "Today's log file not found."


def get_date_range(command):
    dateArray = []   
    today = datetime.now()
    if command == 'yesterday':
        yesterday = today - timedelta(days=1)
        if yesterday.weekday() >= 5:
            last_weekday = today - timedelta(days=today.weekday() - 4)
            speak_with_polly(f"The last weekday was: {last_weekday.strftime('%Y-%m-%d')}") 
            dateArray.append(last_weekday.strftime('%Y-%m-%d'))  # Append formatted date
            return dateArray 
        else:   
            dateArray.append(yesterday.strftime('%Y-%m-%d'))
            return dateArray  # Return as an array
    
    elif command == 'today':
        if today.weekday() >= 5:
            last_weekday = today - timedelta(days=today.weekday() - 4)
            speak_with_polly(f"The last weekday was: {last_weekday.strftime('%Y-%m-%d')}")
            dateArray.append(last_weekday.strftime('%Y-%m-%d'))  # Append formatted date
            return dateArray 
        else:
            dateArray.append(today.strftime('%Y-%m-%d'))
            return dateArray 
    
    elif command == 'week':
        for i in range(7):
            day = today + timedelta(days=i)
            if day.weekday() < 5:  # Monday = 0, Tuesday = 1, ..., Friday = 4
                dateArray.append(day.strftime('%Y-%m-%d'))
        return dateArray  # Return the array of weekdays
    
    return dateArray

def load_and_analyze_logs(command, keyword):
    date_range = get_date_range(command)
    all_logs = ""

    for date in date_range:
        logs = load_logs(date)
        if logs:
            all_logs += f"\nLogs for {date}:\n{logs}\n"
        else:
            all_logs += f"\nNo logs found for {date}\n"

    if all_logs:
        analysis = gpt_logs(keyword, all_logs)
        speak_with_polly(f"Here's the {keyword} of the logs: {analysis}")
    else:
        speak_with_polly("No logs were found for the specified date range.")

def start_trading_bot():
    try:
        # Get the current directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Construct the path to mainV2.py
        bot_script_path = os.path.join(current_dir, 'mainV2.py')
        
        # Start the trading bot as a subprocess using python3
        process = subprocess.Popen(['python3', bot_script_path])
        
        # Save the PID to a file
        pid_file_path = '/tmp/trading-bot-process.pid'
        with open(pid_file_path, 'w') as f:
            f.write(str(process.pid))
        
        speak_with_polly("Trading bot has been started successfully.")
        return "Trading bot started with PID: " + str(process.pid)
    except Exception as e:
        error_message = f"Failed to start trading bot. Error: {str(e)}"
        speak_with_polly(error_message)
        return error_message

def stop_trading_bot():
    try:
        pid_file_path = '/tmp/trading-bot-process.pid'
        
        # Check if the PID file exists
        if not os.path.exists(pid_file_path):
            speak_with_polly("Trading bot is not running.")
            return "Trading bot is not running."
        
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
            speak_with_polly("Trading bot was forcefully terminated.")
        except OSError:
            # Process has terminated
            speak_with_polly("Trading bot has been stopped successfully.")
        
        # Remove the PID file
        os.remove(pid_file_path)
        
        return "Trading bot stopped."
    except Exception as e:
        error_message = f"Failed to stop trading bot. Error: {str(e)}"
        speak_with_polly(error_message)
        return error_message

import re
from datetime import datetime, timedelta
import threading

def monitor_unsold_stock(symbol, purchase_time, purchase_price):
    def check_stock():
        current_time = datetime.now()
        log_file = f"{current_time.strftime('%Y-%m-%d')}app.log"
        
        try:
            with open(log_file, 'r') as file:
                logs = file.readlines()
            
            # Check if the stock has been sold
            sold = any(f"Sold {symbol}" in line for line in logs)
            
            if not sold:
                elapsed_time = current_time - purchase_time
                
                if elapsed_time > timedelta(hours=1):
                    message = f"Alert: The stock {symbol} has not sold after one hour. "
                    message += f"Purchase time: {purchase_time}, Purchase price: ${purchase_price:.2f}"
                    
                    speak_with_polly(message)
                    print(message)
                    
                    # You might want to add logic here to decide whether to sell the stock
                    # For example:
                    # if current_price < purchase_price * 0.95:  # 5% loss
                    #     sell_stock(symbol)
                else:
                    # If less than an hour has passed, schedule the next check
                    remaining_time = timedelta(hours=1) - elapsed_time
                    timer = threading.Timer(remaining_time.total_seconds(), check_stock)
                    timer.start()
        
        except FileNotFoundError:
            print(f"Log file {log_file} not found.")
        except Exception as e:
            print(f"An error occurred: {str(e)}")
    
    # Start the initial check
    check_stock()

def stock_bought_handler(symbol, price):
    purchase_time = datetime.now()
    monitor_unsold_stock(symbol, purchase_time, price)
    message = f"Started monitoring {symbol} bought at ${price:.2f}"
    speak_with_polly(message)
    print(message)

# Example usage:
# When a stock is bought, call stock_bought_handler
# stock_bought_handler("AAPL", 150.75)




# Function to send the log data to GPT and get an explanation
def gpt_logs(keyword, log_text):
    response = openai.Completion.create(
        model="gpt-4",  # you can switch to another model like gpt-3.5-turbo
        prompt=f"{keyword} the following logs in simple terms:\n\n{log_text}",
        max_tokens=300  # Adjust token limit based on the log size
    )
    return response.choices[0].text.strip()


def currently_trading():
    pid_file_path = '/tmp/trading-bot-process.pid'
    if is_process_running(pid_file_path):
        return "Process is running."
    else:
        return "Process is not running."


def get_time_of_day():
    current_hour = datetime.now().hour  # Get the current hour (0-23)

    if 5 <= current_hour < 12:
        return "morning"
    elif 12 <= current_hour < 18:
        return "afternoon"
    else:
        return "evening"


def get_prompts():
    return "Here are the list of prompts: 'read logs', 'are we trading', 'start trade', 'how did we do today'"


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
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=8000)
    stream.start_stream()
    
    print("Listening for voice commands...")
    
    while True:
        data = stream.read(8192, exception_on_overflow=False)
        if recognizer.AcceptWaveform(data):
            result = recognizer.Result()
            text = json.loads(result)["text"]
            if text:
                print(f"Recognized command: {text}")
                return text.lower()


# Main function that responds to commands
def main():
    while True:
        voice_command = recognize_voice()
        adjectives = ["read", "explain", "summarize"]
        if "jarvis" in voice_command:
            start = f"Hey Sola, good {get_time_of_day()}. What can I do for you today?"
            speak_with_polly(start)
            speak_with_polly(get_prompts())
            voice_command = recognize_voice()
            if any(adj in voice_command for adj in adjectives) and "logs" in voice_command:
                picked_date = get_date_range('today')
                logs = load_logs(picked_date)

                if logs != "No logs found.":  # Ensure we're checking the content of logs
                    if "read" in voice_command:
                        speak_with_polly("Reading log content.")
                    elif "explain" in voice_command:
                        speak_with_polly("Explaining log content.")
                    elif "summarize" in voice_command:
                        speak_with_polly("Summarizing log content.")
                    for adj in adjectives:
                        if adj in voice_command:
                            gpt_logs(adj, logs)  # Pass the adjective as the mode to process the logs
                            speak_with_polly()

                else:
                    speak_with_polly("Log file not found.")
            
            elif "today" in voice_command and "logs" in voice_command:
                get_date_range("today")

            elif "exit" in voice_command:
                speak_with_polly("Exiting the program.")
                break
            else:
                speak_with_polly("Unrecognized command. Please say 'read logs', 'explain logs', or 'exit'.")


if __name__ == "__main__":
    main()
