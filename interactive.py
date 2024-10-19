import openai
import pyttsx3
import os
import boto3
from datetime import datetime
from playsound import playsound
import vosk
import sys
import json
import pyaudio

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
def read_logs(log_file):
    if os.path.exists(log_file):
        with open(log_file, 'r') as file:
            logs = file.read()
        return logs
    else:
        return "Log file not found."


# Function to send the log data to GPT and get an explanation
def explain_logs(log_text):
    response = openai.Completion.create(
        model="gpt-4",  # you can switch to another model like gpt-3.5-turbo
        prompt=f"Explain the following logs in simple terms:\n\n{log_text}",
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


# def recognize_voice():
#     # Initialize PyAudio
#     audio = pyaudio.PyAudio()
    
#     # Open the stream with appropriate settings
#     stream = audio.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=4096)
    
#     print("Listening for command...")
    
#     while True:
#         try:
#             data = stream.read(4096)  # Adjust buffer size
#             if recognizer.AcceptWaveform(data):
#                 command = recognizer.Result()
#                 print(f"Command received: {command}")
#                 return command.lower()
#         except IOError as e:
#             if e[1] == paInputOverflowed:
#                 print("Input overflowed. Retrying...")
#                 continue
#             else:
#                 print("Error:", str(e))
#                 break

# Main function that responds to commands
def main(log_file):
   

    while True:
        voice_command = recognize_voice()

        if "jarvis" in voice_command:
            start = f"Hey Sola, good {get_time_of_day()}. What can I do for you today?"
            speak_with_polly(start)
            speak_with_polly(get_prompts())
            voice_command = recognize_voice()
            if "read" in voice_command and "logs" in voice_command:
                logs = read_logs(log_file)
                if logs != "Log file not found.":
                    speak_with_polly("Reading log content.")
                    speak_with_polly(logs)
                else:
                    speak_with_polly("Log file not found.")
            elif "explain" in voice_command and "logs" in voice_command:
                logs = read_logs(log_file)
                if logs != "Log file not found.":
                    explanation = explain_logs(logs)
                    speak_with_polly("Here is an explanation of the logs.")
                    speak_with_polly(explanation)
                else:
                    speak_with_polly("Log file not found.")
            elif "exit" in voice_command:
                speak_with_polly("Exiting the program.")
                break
            else:
                speak_with_polly("Unrecognized command. Please say 'read logs', 'explain logs', or 'exit'.")


if __name__ == "__main__":
    log_file_path = "path_to_your_log_file.log"
    main(log_file_path)
