
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
from openai import OpenAI

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

openai = OpenAI(api_key=get_parameter_value('/openai/api-key'))
# Set your OpenAI API key


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
        speak_with_polly("Today's log file not found.")
        return None


def get_date_range(command):
    dateArray = []   
    today = datetime.now()
    if 'yesterday' in command:
        yesterday = today - timedelta(days=1)
        if yesterday.weekday() >= 5:
            last_weekday = today - timedelta(days=today.weekday() - 4)
            speak_with_polly(f"The last weekday was: {last_weekday.strftime('%Y-%m-%d')}") 
            dateArray.append(last_weekday.strftime('%Y-%m-%d'))  # Append formatted date
            return dateArray 
        else:   
            dateArray.append(yesterday.strftime('%Y-%m-%d'))
            return dateArray  # Return as an array
    
    elif 'today' in command:
        if today.weekday() >= 5:
            last_weekday = today - timedelta(days=today.weekday() - 4)
            speak_with_polly(f"The last weekday was: {last_weekday.strftime('%Y-%m-%d')}")
            dateArray.append(last_weekday.strftime('%Y-%m-%d'))  # Append formatted date
            return dateArray 
        else:
            dateArray.append(today.strftime('%Y-%m-%d'))
            return dateArray 
    
    elif 'week' in command:
        for i in range(7):
            day = today + timedelta(days=i)
            if day.weekday() < 5:  # Monday = 0, Tuesday = 1, ..., Friday = 4
                dateArray.append(day.strftime('%Y-%m-%d'))
        return dateArray  # Return the array of weekdays
    
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

    if all_logs:
        analysis = gpt_logs(keyword, all_logs)
        speak_with_polly(f"Here's the {keyword} of the logs: {analysis}")
    else:
        speak_with_polly("No logs were found for the specified date range.")




def start_trading_bot(mode, group, dryrun, user_id):
    try:
        # Get the current directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Construct the path to mainV2.py
        bot_script_path = os.path.join(current_dir, 'mainV2.py')
        
        # Start the trading bot as a subprocess using python3
        process = subprocess.Popen(['python3', bot_script_path, '-m', mode, '-g', group, '-d', dryrun, '-u', user_id])
        
        speak_with_polly("bot has been started successfully.")
        return "Trading bot started with PID: " + str(process.pid)
    except Exception as e:
        error_message = f"Failed to start bot. Error: {str(e)}"
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




# Function to send the log data to GPT and get an explanation
def gpt_logs(keyword, log_text):
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",  # Updated to "gpt-4-turbo" since "gpt-4o-mini" might be incorrect or unavailable
        messages=[  # Messages should be a list of dicts
            {"role": "user", "content": f"{keyword} the following logs in simple terms:\n\n{log_text}"}
        ]
    )
    print(response.choices[0].message.content)
    return response.choices[0].message.content

    #return response.choices[0].message['content']


def currently_trading():
    pid_file_path = '/tmp/trading-bot-process.pid'
    if is_process_running(pid_file_path):
        speak_with_polly("The trading bot is running.")
    else:
        speak_with_polly("The trading bot is not running.")


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



# Main function that responds to commands
def main():

    #start_trading_bot("upcoming-earnings", "biopharmaceutical")
    # time.sleep(10)
    # currently_trading()
    # # time.sleep(10)
    # # stop_trading_bot()
    # hour = load_recent_logs()
    
    # # analyze_logs("explain", all_logs)
    # analyze_logs("summarize", hour)
    adjectives = ["read", "explain", "summarize"]
    

    while True:
        voice_command = recognize_voice()
        adjectives = ["read", "explain", "summarize"]
        if "jarvis" in voice_command:
            start = f"Hey Sola, good {get_time_of_day()}. What can I do for you today?"
            speak_with_polly(start)
            speak_with_polly(get_prompts())
            voice_command = recognize_voice()
            if any(adj in voice_command for adj in adjectives) and "today" in voice_command:
                  all_logs = load_logs_for_analysis("today")
                  analyze_logs("summarize", all_logs)

            elif any(adj in voice_command for adj in adjectives) and "yesterday" in voice_command:
                  all_logs = load_logs_for_analysis("yesterday")
                  analyze_logs("summarize", all_logs)

            elif any(adj in voice_command for adj in adjectives) and "week" in voice_command:
                  all_logs = load_logs_for_analysis("week")
                  analyze_logs("summarize", all_logs)

            elif "are we trading" in voice_command:
                  currently_trading()
            
            elif "start" in voice_command:
                mode = ""
                group = ""
                users = 1
                dryrun = True
                groups_available = ["biopharmaceutical", "upcoming-earnings", "most-popular-under-25", "technology"]
                modes_available = ["granular", "non-granular"]

                
                speak_with_polly("Please specify the mode as granular or non-granular.")
                voice_command = recognize_voice()
                
                while not any(m in voice_command for m in modes_available):
                    speak_with_polly("Specify the mode as granular or non-granular. Say skip or next to abort.")
                    voice_command = recognize_voice()
                    if "skip" in voice_command or "next" in voice_command:
                        speak_with_polly("Mode selection aborted.")
                        break
                else:
                    mode = next((m for m in modes_available if m in voice_command), "granular")

                
                speak_with_polly("Now, specify the group. Options are biopharmaceutical, upcoming-earnings, most-popular-under-25, or technology.")
                voice_command = recognize_voice()
                
                while not any(g in voice_command for g in groups_available):
                    speak_with_polly("Specify the group. Say skip or next to abort.")
                    voice_command = recognize_voice()
                    if "skip" in voice_command or "next" in voice_command:
                        speak_with_polly("Group selection aborted.")
                        break
                else:
                    group = next((g for g in groups_available if g in voice_command), "technology")
                
                speak_with_polly("how many bots do you need to be spun up. you can have between 1 to 100")
                voice_command = recognize_voice()
                
                while not any(n in voice_command for n in range(100)):
                    speak_with_polly("Specify the group. Say skip or next to abort.")
                    voice_command = recognize_voice()
                    if "skip" in voice_command or "next" in voice_command:
                        speak_with_polly("Group selection aborted.")
                        break
                else:
                    n = next((n for n in str(range(100)) if n in voice_command), 1)
                
                if mode and group:
                    for user in user_list[:int(n)]:
                        start_trading_bot(mode=mode, group=group, dryrun=dryrun, user_id=user)
                else:
                    speak_with_polly("Trading bot was not started due to missing mode or group.")

            elif "stop" in voice_command:
                  stop_trading_bot()
            elif "exit" in voice_command:
                speak_with_polly("Exiting the program.")
                break

            elif "kill" in voice_command:
                try:
                    speak_with_polly("Opening a terminal to show the command to kill the trading bot")
                    command = "ps aux | grep '[p]ython.*main.py' | awk '{print $2}'"
                    speak_with_polly("To kill the trading bot, copy this command and paste it in your terminal:")
                    speak_with_polly(command)
                    speak_with_polly("Then use: kill -9 followed by the process ID shown")
                except Exception as e:
                    speak_with_polly(f"Error providing kill command: {str(e)}")





if __name__ == "__main__":
    main()
