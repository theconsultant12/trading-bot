pip install --upgrade pip setuptools wheel
needed for robin-stocks install
brew install tensorflow

# Interactive Voice Assistant with Log Analysis and Stock Prediction

This project implements an interactive voice assistant that can perform various tasks, including log analysis, voice recognition, and stock price prediction. The assistant, named "Jarvis," uses OpenAI's GPT models for natural language processing, AWS Polly for text-to-speech functionality, and machine learning models for stock prediction.

## Features

1. Voice Recognition: Uses the Vosk library for offline speech recognition.
2. Text-to-Speech: Utilizes AWS Polly for high-quality speech synthesis.
3. Log Analysis: Can read, explain, and summarize log files using OpenAI's GPT models.
4. Date Range Selection: Supports commands for "today," "yesterday," and "week" to analyze logs from specific time periods.
5. Process Monitoring: Can check if a specific process (trading bot) is currently running.
6. Stock Price Prediction: Uses machine learning models to predict stock prices.

## Main Components

### 1. Voice Recognition and Interaction (interactive.py)
- Uses Vosk for offline speech recognition
- Continuously listens for voice commands
- Implements the main interaction loop with the user

### 2. Log Analysis
- Reads log files from specified date ranges
- Uses OpenAI's GPT models to analyze and explain log content

### 3. Text-to-Speech
- Uses AWS Polly to convert text responses to speech

### 4. Date Handling
- Implements logic to handle date ranges for log retrieval
- Accounts for weekends when selecting "yesterday" or "today"

### 5. AWS Integration
- Uses AWS Systems Manager Parameter Store to securely store and retrieve API keys

### 6. Stock Trading and Prediction (mainV2.py)
- Implements a trading bot that can be run as a separate process
- Integrates with the stock prediction module

### 7. Stock Price Prediction (predict_stock.py)
- Uses machine learning models (LSTM) to predict stock prices
- Handles data preprocessing, model training, and prediction

## Setup and Installation

1. Install Miniconda or Anaconda if you haven't already:
   - Download from [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or [Anaconda](https://www.anaconda.com/products/distribution)

2. Create the conda environment from the environment.yml file:

```bash
conda env create -f environment.yml
```

3. Activate the environment:

```bash
conda activate voice-assistant
```

4. Additional Setup Steps:
   - Set up the Vosk model in the specified path
   - Configure AWS credentials for Polly and Systems Manager
   - Store the OpenAI API key in AWS Systems Manager Parameter Store
   - Ensure you have sufficient historical stock data for training the prediction models

## Dependencies

All dependencies are managed through the conda environment. Key packages include:
- openai
- pyttsx3
- boto3
- playsound
- vosk
- pyaudio
- pandas
- numpy
- scikit-learn
- tensorflow
- yfinance

To update dependencies, modify the environment.yml file and run:

```bash
conda env update -f environment.yml --prune
```

## Note

This project demonstrates integration of various technologies including speech recognition, natural language processing, cloud services, and machine learning to create an interactive voice assistant capable of performing complex tasks like log analysis and stock price prediction. The modular structure allows for easy expansion and addition of new features.

