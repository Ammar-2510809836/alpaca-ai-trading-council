import logging

import pandas as pd


def calculate_ema(df: pd.DataFrame, periods=(100,), column="close"):
    if df is None or df.empty:
        logging.warning("EMA calculation received empty dataframe")
        return df

    if column not in df.columns:
        logging.error(f"EMA calculation failed, {column} column missing")
        return df

    df = df.copy()
    for period in periods:
        df[f"EMA_{period}"] = df[column].ewm(span=period, adjust=False).mean()

    return df


def check_price_vs_ema(df: pd.DataFrame, ema_period=100):
    if df is None or df.empty:
        return None

    ema_col = f"EMA_{ema_period}"
    if ema_col not in df.columns:
        return None

    latest_close = df["close"].iloc[-1]
    latest_ema = df[ema_col].iloc[-1]

    if latest_close > latest_ema:
        return "above"
    elif latest_close < latest_ema:
        return "below"
    return None
