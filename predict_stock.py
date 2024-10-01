import csv
import urllib.request
import datetime
import pandas as pd
import time
from datetime import timedelta
from matplotlib import pyplot as plt
import numpy as np
import logging
from tensorflow.keras.models import Sequential
from tensorflow.keras.optimizers import Adam
from tensorflow.keras import layers

def download_csv(stock, days=100):
    logging.info(f"Downloading CSV data for {stock}")
    
    now = datetime.datetime.now()
    start_date = now - timedelta(days=days)
    start_timestamp = int(time.mktime(start_date.timetuple()))
    end_timestamp = int(time.mktime(now.timetuple()))
    
    url = f"https://query1.finance.yahoo.com/v7/finance/download/{stock}?period1={start_timestamp}&period2={end_timestamp}&interval=1d&events=history&includeAdjustedClose=true"
    urllib.request.urlretrieve(url, f"{stock}.csv")
    
    logging.info(f"Downloaded CSV data for {stock}")

def str_to_datetime(s):
    split = s.split('-')
    year, month, day = int(split[0]), int(split[1]), int(split[2])
    return datetime.datetime(year=year, month=month, day=day)

def df_to_windowed_df(dataframe, n=3):
    logging.info("Converting DataFrame to windowed DataFrame")
    
    dates = []
    X, Y = [], []

    for i in range(n, len(dataframe)):
        x = dataframe.iloc[i-n:i]['Close'].to_numpy()
        y = dataframe.iloc[i]['Close']
        
        dates.append(dataframe.index[i])
        X.append(x)
        Y.append(y)
    
    ret_df = pd.DataFrame({})
    ret_df['Target Date'] = dates
    X = np.array(X)
    
    for i in range(0, n):
        ret_df[f'Target-{n-i}'] = X[:, i]
    
    ret_df['Target'] = Y
    
    logging.info("Converted DataFrame to windowed DataFrame")
    return ret_df

def windowed_df_to_date_X_y(windowed_dataframe):
    logging.info("Converting windowed DataFrame to X and Y datasets")
    
    df_as_np = windowed_dataframe.to_numpy()

    dates = df_as_np[:, 0]

    middle_matrix = df_as_np[:, 1:-1]
    X = middle_matrix.reshape((len(dates), middle_matrix.shape[1], 1))

    Y = df_as_np[:, -1]

    logging.info("Converted windowed DataFrame to X and Y datasets")
    return dates, X.astype(np.float32), Y.astype(np.float32)

def run_lstm(stock):
    logging.info(f"Running LSTM model for {stock}")
    
    download_csv(stock, days=100)

    df = pd.read_csv(f'{stock}.csv')
    df = df[['Date', 'Close']]
    df['Date'] = df['Date'].apply(str_to_datetime)
    df.index = df.pop('Date')

    windowed_df = df_to_windowed_df(df, n=3)
    dates, X, y = windowed_df_to_date_X_y(windowed_df)

    q_80 = int(len(dates) * .8)
    q_90 = int(len(dates) * .9)

    dates_train, X_train, y_train = dates[:q_80], X[:q_80], y[:q_80]
    dates_val, X_val, y_val = dates[q_80:q_90], X[q_80:q_90], y[q_80:q_90]
    dates_test, X_test, y_test = dates[q_90:], X[q_90:], y[q_90:]

    model = Sequential([layers.Input((3, 1)),
                        layers.LSTM(64),
                        layers.Dense(32, activation='relu'),
                        layers.Dense(32, activation='relu'),
                        layers.Dense(1)])

    model.compile(loss='mse', 
                  optimizer=Adam(learning_rate=0.001),
                  metrics=['mean_absolute_error'])

    logging.info("Training LSTM model")
    model.fit(X_train, y_train, validation_data=(X_val, y_val), epochs=100)
    logging.info("Completed training LSTM model")

    latest_data = df.tail(3)['Close'].to_numpy().reshape((1, 3, 1)).astype(np.float32)
    predicted_price = model.predict(latest_data)

    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")

    logging.info(f"Predicted end-of-day price for {today}: {predicted_price[0][0]}")

    df.loc[now] = predicted_price[0][0]

    plt.figure(figsize=(10, 6))
    plt.plot(df.index[:-1], df['Close'][:-1], label='Historical Prices')
    plt.plot(df.index[-2:], df['Close'][-2:], 'r--', label=f'Predicted Price for {today}')
    plt.xlabel('Date')
    plt.ylabel('Close Price')
    plt.title(f"{stock} Stock Price Prediction for {today}")
    plt.legend()
    plt.grid(True)
    plt.ion()
    plt.show()
    
    logging.info(f"Plotted the stock price prediction for {stock}")
    return predicted_price[0][0]
