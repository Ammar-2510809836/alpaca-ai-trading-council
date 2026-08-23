import pandas as pd


def dominant_high(df: pd.DataFrame, break_row: int) -> int:
    idx = break_row
    while idx > 0:
        left = idx - 1
        if df.at[left, "high"] > df.at[idx, "high"] and df.at[left, "low"] >= df.at[idx, "low"]:
            idx = left
        else:
            break
    return idx


def dominant_low(df: pd.DataFrame, break_row: int) -> int:
    idx = break_row
    while idx > 0:
        left = idx - 1
        if df.at[left, "low"] < df.at[idx, "low"] and df.at[left, "high"] <= df.at[idx, "high"]:
            idx = left
        else:
            break
    return idx


def detect_fractals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reset_index(drop=True).copy()

    if len(df) < 2:
        raise ValueError("Need at least two rows to seed fractals")

    df["curr_fh"] = None
    df["curr_fl"] = None
    df["structure_break"] = False
    df["break_type"] = None
    df["fractal_trend"] = "neutral"
    df["state"] = "neutral"

    fh_idx = 0 if df.at[0, "high"] >= df.at[1, "high"] else 1
    fl_idx = 0 if df.at[0, "low"] <= df.at[1, "low"] else 1

    fh = df.at[fh_idx, "high"]
    fl = df.at[fl_idx, "low"]

    trend = "neutral"
    state = "neutral"
    provisional_val = None

    for i in range(2, len(df)):
        hi = df.at[i, "high"]
        lo = df.at[i, "low"]

        structure_break = False
        break_type = None

        if state == "neutral":
            if lo < fl:
                structure_break = True
                break_type = "bearish_break"
                dom_idx = dominant_high(df, i)
                fh = df.at[dom_idx, "high"]
                fl = lo
                provisional_val = lo
                state = "await_pullback_bearish"
                trend = "bearish"
            elif hi > fh:
                structure_break = True
                break_type = "bullish_break"
                dom_idx = dominant_low(df, i)
                fl = df.at[dom_idx, "low"]
                fh = hi
                provisional_val = hi
                state = "await_pullback_bullish"
                trend = "bullish"

        elif state == "await_pullback_bearish":
            if lo < provisional_val:
                provisional_val = lo
                fl = lo
            if lo > df.at[i - 1, "low"]:
                fl = df.at[i - 1, "low"]
                state = "neutral"

        elif state == "await_pullback_bullish":
            if hi > provisional_val:
                provisional_val = hi
                fh = hi
            if hi < df.at[i - 1, "high"]:
                fh = df.at[i - 1, "high"]
                state = "neutral"

        df.at[i, "curr_fh"] = fh
        df.at[i, "curr_fl"] = fl
        df.at[i, "structure_break"] = structure_break
        df.at[i, "break_type"] = break_type
        df.at[i, "fractal_trend"] = trend
        df.at[i, "state"] = state

    return df
