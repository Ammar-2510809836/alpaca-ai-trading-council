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


def calculate_ema_crossover(df: pd.DataFrame, fast_period: int = 9, slow_period: int = 21, column: str = "close") -> dict:
    """Calculates EMA 9 and EMA 21 and detects bullish/bearish crossover events and regime."""
    if df is None or df.empty or len(df) < slow_period + 2:
        return {
            "crossover": None,
            "regime": "neutral",
            "fast_ema": None,
            "slow_ema": None,
            "spread_pct": 0.0,
        }

    df_calc = calculate_ema(df, periods=(fast_period, slow_period), column=column)
    fast_col = f"EMA_{fast_period}"
    slow_col = f"EMA_{slow_period}"

    if fast_col not in df_calc.columns or slow_col not in df_calc.columns:
        return {
            "crossover": None,
            "regime": "neutral",
            "fast_ema": None,
            "slow_ema": None,
            "spread_pct": 0.0,
        }

    fast_series = df_calc[fast_col]
    slow_series = df_calc[slow_col]

    curr_fast = float(fast_series.iloc[-1])
    curr_slow = float(slow_series.iloc[-1])
    prev_fast = float(fast_series.iloc[-2])
    prev_slow = float(slow_series.iloc[-2])

    crossover = None
    if prev_fast <= prev_slow and curr_fast > curr_slow:
        crossover = "bullish"
    elif prev_fast >= prev_slow and curr_fast < curr_slow:
        crossover = "bearish"

    regime = "bullish" if curr_fast > curr_slow else ("bearish" if curr_fast < curr_slow else "neutral")
    spread_pct = ((curr_fast / curr_slow - 1) * 100) if curr_slow > 0 else 0.0

    return {
        "crossover": crossover,
        "regime": regime,
        "fast_ema": round(curr_fast, 4),
        "slow_ema": round(curr_slow, 4),
        "spread_pct": round(spread_pct, 4),
    }
