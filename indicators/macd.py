import logging

import pandas as pd


def calculate_macd(
    df: pd.DataFrame,
    fast_period=12,
    slow_period=26,
    signal_period=9,
):
    if df is None or df.empty:
        logging.warning("MACD calculation received empty dataframe")
        return None, None, None

    if "close" not in df.columns:
        logging.error("MACD calculation failed, close column missing")
        return None, None, None

    close = df["close"]
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()

    macd = ema_fast - ema_slow
    signal = macd.ewm(span=signal_period, adjust=False).mean()
    histogram = macd - signal

    return macd, signal, histogram


def detect_macd_crossover(macd: pd.Series, signal: pd.Series):
    if macd is None or signal is None:
        return None

    if len(macd) < 2 or len(signal) < 2:
        return None

    prev_macd = macd.iloc[-2]
    prev_signal = signal.iloc[-2]
    curr_macd = macd.iloc[-1]
    curr_signal = signal.iloc[-1]

    if prev_macd <= prev_signal and curr_macd > curr_signal:
        return "bullish"

    if prev_macd >= prev_signal and curr_macd < curr_signal:
        return "bearish"

    return None


def resample_ohlc(df: pd.DataFrame, rule="1D") -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule, on="time" if "time" in df.columns else None).agg(agg)
    return out.dropna(subset=["close"]).reset_index()
