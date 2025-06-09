import logging
from pathlib import Path
from typing import Tuple, Union

import numpy as np
import pandas as pd
from keras import layers
from keras.models import Sequential
from keras.optimizers import Adam
from matplotlib import pyplot as plt


# --------------------------------------------------------------------------- #
# Utility helpers                                                             #
# --------------------------------------------------------------------------- #
def _load_csv_data(symbol: str,
                   base_dir: Union[str, Path] = "data") -> pd.DataFrame:
    csv_path = Path(base_dir) / f"{symbol}_prices.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"{csv_path} not found—place your CSV there.")

    df = pd.read_csv(csv_path, usecols=["timestamp", "close"])
    df.rename(columns={"timestamp": "Date", "close": "Close"}, inplace=True)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)

    # --- NEW: force numeric & drop bad rows ---------------------------------
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df[np.isfinite(df["Close"])]        # drops NaN, inf, -inf

    if len(df) < 4:                          # need ≥ n+1 rows (n = 3)
        raise ValueError(f"Not enough clean data in {csv_path}")

    df.sort_values("Date", inplace=True)
    df.set_index("Date", inplace=True)
    df = df[~df.index.duplicated(keep="last")]
    return df


def _df_to_windowed_df(df: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """Convert a price series to an n‑step windowed DataFrame (supervised format)."""
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
    Train a 3‑step‑look‑back LSTM on close prices in `data/<SYMBOL>.csv`
    and return the predicted next close price.
    """
    logging.info("Loading CSV for %s", symbol)
    df = _load_csv_data(symbol, base_dir)

    logging.info("Preparing windowed dataset")
    wdf = _df_to_windowed_df(df, n=3)
    dates, X, y = _windowed_df_to_date_X_y(wdf)

    # Train/val/test split (80 / 10 / 10)
    q80, q90 = int(0.8 * len(X)), int(0.9 * len(X))
    X_train, y_train = X[:q80], y[:q80]
    X_val, y_val = X[q80:q90], y[q80:q90]
    X_test, y_test = X[q90:], y[q90:]

    model = Sequential([
        layers.Input((3, 1)),
        layers.LSTM(64),
        layers.Dense(32, activation='relu'),
        layers.Dense(32, activation='relu'),
        layers.Dense(1),
    ])
    model.compile(loss='mse',
                  optimizer=Adam(learning_rate=0.001),
                  metrics=['mean_absolute_error'])

    logging.info("Training LSTM (%d training samples)", len(X_train))
    model.fit(X_train, y_train,
              validation_data=(X_val, y_val),
              epochs=epochs, verbose=0)
    logging.info("Training complete – MAE on test: %.4f",
                 model.evaluate(X_test, y_test, verbose=0)[1])

    # Predict the next close
    latest_window = df["Close"].tail(3).to_numpy().reshape((1, 3, 1)).astype(np.float32)
    predicted_price = float(model.predict(latest_window, verbose=0)[0][0])

    # Build & save chart every time
    next_ts = df.index[-1] + pd.Timedelta(days=1)
    df_plot = df.copy()
    df_plot.loc[next_ts] = predicted_price

    plt.figure(figsize=(10, 6))
    plt.plot(df_plot.index[:-1], df_plot["Close"][:-1], label="Historical Prices")
    plt.plot(df_plot.index[-2:], df_plot["Close"][-2:], "r--",
             label=f"Predicted ({next_ts.date()})")
    plt.title(f"{symbol} – next‑day close prediction")
    plt.xlabel("Date")
    plt.ylabel("Close Price")
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
