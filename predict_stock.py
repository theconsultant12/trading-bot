import logging
from pathlib import Path
from typing import Tuple, Union

import numpy as np
import pandas as pd
from keras import layers
from keras.models import Sequential
from keras.optimizers import Adam
from keras.callbacks import EarlyStopping
from matplotlib import pyplot as plt
from sklearn.preprocessing import MinMaxScaler


LOOKBACK = 20  # number of prior closing prices fed as input features


# --------------------------------------------------------------------------- #
# Utility helpers                                                             #
# --------------------------------------------------------------------------- #
def _load_csv_data(symbol: str,
                   base_dir: Union[str, Path] = "data") -> pd.DataFrame:
    csv_path = Path(base_dir) / f"{symbol}_prices.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} not found -- place your CSV there.")

    df = pd.read_csv(csv_path, usecols=["timestamp", "c"])
    df.rename(columns={"timestamp": "Date", "c": "Close"}, inplace=True)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)

    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df[np.isfinite(df["Close"])]

    if len(df) < LOOKBACK + 1:
        raise ValueError(
            f"Not enough clean data in {csv_path} "
            f"(need >= {LOOKBACK + 1} rows, got {len(df)})"
        )

    df.sort_values("Date", inplace=True)
    df.set_index("Date", inplace=True)
    df = df[~df.index.duplicated(keep="last")]
    return df


def _df_to_windowed_df(df: pd.DataFrame, n: int = LOOKBACK) -> pd.DataFrame:
    """Convert a price series to an n-step windowed DataFrame (supervised format)."""
    dates, X, Y = [], [], []
    for i in range(n, len(df)):
        window = df.iloc[i - n:i]["Close"].to_numpy()
        target = df.iloc[i]["Close"]
        dates.append(df.index[i])
        X.append(window)
        Y.append(target)

    X = np.array(X)
    out = pd.DataFrame({"Target Date": dates, "Target": Y})
    for i in range(n):
        out[f"Target-{n - i}"] = X[:, i]
    return out


def _windowed_df_to_date_X_y(
        windowed_df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split the windowed DataFrame into date, X, y numpy arrays."""
    arr = windowed_df.to_numpy()
    dates = arr[:, 0]
    X = arr[:, 2:].astype(np.float32).reshape((len(dates), -1, 1))  # (m, n, 1)
    y = arr[:, 1].astype(np.float32)
    return dates, X, y


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
def run_lstm(symbol: str,
             base_dir: Union[str, Path] = "data",
             *,
             epochs: int = 100,
             show_plot: bool = True) -> float:
    """
    Train a LOOKBACK-step LSTM on normalised close prices and return
    the predicted next close price in original dollar units.

    Improvements over the original:
    - MinMaxScaler normalisation so the network handles any price magnitude
    - 20-step lookback (vs the original 3) for better trend context
    - EarlyStopping to prevent overfitting on small datasets
    """
    logging.info("Loading CSV for %s", symbol)
    df = _load_csv_data(symbol, base_dir)

    # Normalise to [0, 1] -- required for stable LSTM training across price magnitudes
    scaler = MinMaxScaler()
    df["Close"] = scaler.fit_transform(df[["Close"]])

    logging.info("Preparing windowed dataset (lookback=%d)", LOOKBACK)
    wdf = _df_to_windowed_df(df, n=LOOKBACK)
    dates, X, y = _windowed_df_to_date_X_y(wdf)

    # Train/val/test split (80 / 10 / 10)
    q80, q90 = int(0.8 * len(X)), int(0.9 * len(X))
    X_train, y_train = X[:q80], y[:q80]
    X_val, y_val = X[q80:q90], y[q80:q90]
    X_test, y_test = X[q90:], y[q90:]

    model = Sequential([
        layers.Input((LOOKBACK, 1)),
        layers.LSTM(64),
        layers.Dense(32, activation='relu'),
        layers.Dense(32, activation='relu'),
        layers.Dense(1),
    ])
    model.compile(loss='mse',
                  optimizer=Adam(learning_rate=0.001),
                  metrics=['mean_absolute_error'])

    early_stop = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)

    logging.info("Training LSTM (%d training samples)", len(X_train))
    model.fit(X_train, y_train,
              validation_data=(X_val, y_val),
              epochs=epochs,
              callbacks=[early_stop],
              verbose=0)
    logging.info("Training complete -- MAE on test: %.4f",
                 model.evaluate(X_test, y_test, verbose=0)[1])

    # Predict next close (normalised), then inverse-transform to dollar price
    latest_window = df["Close"].tail(LOOKBACK).to_numpy().reshape((1, LOOKBACK, 1)).astype(np.float32)
    predicted_scaled = float(model.predict(latest_window, verbose=0)[0][0])
    predicted_price = float(scaler.inverse_transform([[predicted_scaled]])[0][0])

    # Restore original scale for the chart
    original_close = scaler.inverse_transform(df[["Close"]].values)
    df_original = df.copy()
    df_original["Close"] = original_close

    next_ts = df_original.index[-1] + pd.Timedelta(days=1)
    df_original.loc[next_ts, "Close"] = predicted_price

    plt.figure(figsize=(10, 6))
    plt.plot(df_original.index[:-1], df_original["Close"][:-1], label="Historical Prices")
    plt.plot(df_original.index[-2:], df_original["Close"][-2:], "r--",
             label=f"Predicted ({next_ts.date()})")
    plt.title(f"{symbol} -- next-day close prediction")
    plt.xlabel("Date")
    plt.ylabel("Close Price ($)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    out_dir = Path("stock_graph")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{symbol}.png"
    plt.savefig(out_file, dpi=300, bbox_inches="tight")
    logging.info("Saved plot to %s", out_file)

    if show_plot:
        plt.show()
    plt.close()

    logging.info("Predicted next close for %s: %.2f", symbol, predicted_price)
    return predicted_price
