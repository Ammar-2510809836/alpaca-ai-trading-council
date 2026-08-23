from indicators.ema import calculate_ema
from indicators.fractal_structure import detect_fractals
from indicators.macd import calculate_macd, detect_macd_crossover, resample_ohlc
from indicators.rsi import calculate_rsi, detect_rsi_divergence


def build_technical_context(df, symbol: str) -> dict:
    ctx = {
        "symbol": symbol,
        "price": float(df["close"].iloc[-1]),
        "bars_analyzed": len(df),
        "macd_crossover": None,
        "macd_histogram_trend": None,
        "rsi": None,
        "rsi_bullish_divergence": False,
        "rsi_bearish_divergence": False,
        "htf_daily_trend": None,
        "htf_hourly_trend": None,
        "fractal_trend": None,
        "recent_structure_break": None,
        "swing_low": None,
        "swing_high": None,
    }

    macd, signal, histogram = calculate_macd(df)
    ctx["macd_crossover"] = detect_macd_crossover(macd, signal)
    if histogram is not None and len(histogram) >= 4:
        recent = histogram.iloc[-4:]
        if recent.is_monotonic_increasing:
            ctx["macd_histogram_trend"] = "rising"
        elif recent.is_monotonic_decreasing:
            ctx["macd_histogram_trend"] = "falling"

    df = df.copy()
    df["RSI"] = calculate_rsi(df)
    if df["RSI"] is not None:
        ctx["rsi"] = float(df["RSI"].iloc[-1])
        try:
            diverged = detect_rsi_divergence(df.tail(120))
            ctx["rsi_bullish_divergence"] = bool(diverged["bullish_divergence"].any())
            ctx["rsi_bearish_divergence"] = bool(diverged["bearish_divergence"].any())
        except Exception:
            pass

    hourly = resample_ohlc(df, "1h")
    if len(hourly) >= 60:
        hourly = calculate_ema(hourly, periods=(50,))
        ctx["htf_hourly_trend"] = (
            "bullish" if hourly["close"].iloc[-1] > hourly["EMA_50"].iloc[-1] else "bearish"
        )

    daily = resample_ohlc(df, "1D")
    if len(daily) >= 30:
        daily = calculate_ema(daily, periods=(20,))
        ctx["htf_daily_trend"] = (
            "bullish" if daily["close"].iloc[-1] > daily["EMA_20"].iloc[-1] else "bearish"
        )

    try:
        structured = detect_fractals(df.tail(200))
        ctx["fractal_trend"] = structured["fractal_trend"].iloc[-1]
        last_breaks = structured[structured["structure_break"]]
        if not last_breaks.empty:
            ctx["recent_structure_break"] = last_breaks["break_type"].iloc[-1]
        row = structured.iloc[-1]
        ctx["swing_high"] = float(row["curr_fh"]) if row["curr_fh"] else None
        ctx["swing_low"] = float(row["curr_fl"]) if row["curr_fl"] else None
    except Exception:
        pass

    return ctx


def format_technical_summary(ctx: dict) -> str:
    lines = [
        f"Symbol: {ctx['symbol']}",
        f"Last price: {ctx['price']}",
        f"MACD crossover (latest closed bar): {ctx.get('macd_crossover') or 'none'}",
        f"MACD histogram trend: {ctx.get('macd_histogram_trend') or 'flat'}",
        f"RSI(14): {ctx.get('rsi')}",
        f"Bullish RSI divergence in window: {ctx.get('rsi_bullish_divergence')}",
        f"Bearish RSI divergence in window: {ctx.get('rsi_bearish_divergence')}",
        f"Intraday structure trend (fractals): {ctx.get('fractal_trend')}",
        f"Recent structure break: {ctx.get('recent_structure_break') or 'none'}",
        f"Hourly EMA50 regime: {ctx.get('htf_hourly_trend') or 'insufficient data'}",
        f"Daily EMA20 regime: {ctx.get('htf_daily_trend') or 'insufficient data'}",
        f"Swing high / low reference: {ctx.get('swing_high')} / {ctx.get('swing_low')}",
    ]
    return "\n".join(str(line) for line in lines)


def format_news_summary(news_items: list) -> str:
    if not news_items:
        return "No recent headlines available."

    lines = []
    for item in news_items[:6]:
        headline = item.get("headline", "")
        source = item.get("source", "")
        summary = (item.get("summary") or "").replace("\n", " ")[:220]
        lines.append(f"- [{source}] {headline} :: {summary}")
    return "\n".join(lines)
