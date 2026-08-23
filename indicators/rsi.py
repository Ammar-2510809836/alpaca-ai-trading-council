import logging

import numpy as np
import pandas as pd


def calculate_rsi(df: pd.DataFrame, period=14):
    if df is None or df.empty:
        logging.warning("RSI calculation received empty dataframe")
        return None

    if "close" not in df.columns:
        logging.error("RSI calculation failed, close column missing")
        return None

    delta = df["close"].diff()

    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()

    rsi = np.where(
        roll_down == 0,
        100,
        np.where(
            roll_up == 0,
            0,
            100 - (100 / (1 + roll_up / roll_down)),
        ),
    )

    return pd.Series(np.round(rsi, 2), index=df.index)


def pivot_low(series: pd.Series, left=5, right=5) -> pd.Series:
    values = series.values
    n = len(values)
    pivots = np.zeros(n, dtype=bool)

    for i in range(left, n - right):
        window_val = values[i]
        left_ok = all(window_val < values[i - j] for j in range(1, left + 1))
        right_ok = all(window_val < values[i + j] for j in range(1, right + 1))
        if left_ok and right_ok:
            pivots[i] = True

    return pd.Series(pivots, index=series.index)


def pivot_high(series: pd.Series, left=5, right=5) -> pd.Series:
    values = series.values
    n = len(values)
    pivots = np.zeros(n, dtype=bool)

    for i in range(left, n - right):
        window_val = values[i]
        left_ok = all(window_val > values[i - j] for j in range(1, left + 1))
        right_ok = all(window_val > values[i + j] for j in range(1, right + 1))
        if left_ok and right_ok:
            pivots[i] = True

    return pd.Series(pivots, index=series.index)


def detect_rsi_divergence(df: pd.DataFrame, lbL=5, lbR=5, rangeLower=5, rangeUpper=60):
    df = df.copy()
    df["rsi_pivot_low"] = pivot_low(df["RSI"], lbL, lbR)
    df["rsi_pivot_high"] = pivot_high(df["RSI"], lbL, lbR)

    df["bullish_divergence"] = False
    df["hidden_bullish_divergence"] = False
    df["bearish_divergence"] = False
    df["hidden_bearish_divergence"] = False

    last_pl_i = None
    last_ph_i = None

    for i in range(len(df)):
        if df["rsi_pivot_low"].iloc[i]:
            cur_rsi = df["RSI"].iloc[i]
            cur_price = df["low"].iloc[i]

            if last_pl_i is not None:
                bars_since = i - last_pl_i
                if rangeLower <= bars_since <= rangeUpper:
                    prev_rsi = df["RSI"].iloc[last_pl_i]
                    prev_price = df["low"].iloc[last_pl_i]

                    if cur_price < prev_price and cur_rsi > prev_rsi:
                        df.at[df.index[i], "bullish_divergence"] = True
                    if cur_price > prev_price and cur_rsi < prev_rsi:
                        df.at[df.index[i], "hidden_bullish_divergence"] = True

            last_pl_i = i

        if df["rsi_pivot_high"].iloc[i]:
            cur_rsi = df["RSI"].iloc[i]
            cur_price = df["high"].iloc[i]

            if last_ph_i is not None:
                bars_since = i - last_ph_i
                if rangeLower <= bars_since <= rangeUpper:
                    prev_rsi = df["RSI"].iloc[last_ph_i]
                    prev_price = df["high"].iloc[last_ph_i]

                    if cur_price > prev_price and cur_rsi < prev_rsi:
                        df.at[df.index[i], "bearish_divergence"] = True
                    if cur_price < prev_price and cur_rsi > prev_rsi:
                        df.at[df.index[i], "hidden_bearish_divergence"] = True

            last_ph_i = i

    return df
