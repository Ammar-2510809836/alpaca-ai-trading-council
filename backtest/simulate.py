import argparse
import hashlib
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.ema import calculate_ema
from indicators.macd import calculate_macd
from indicators.rsi import calculate_rsi


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S: float, K: float, T_years: float, sigma: float, r: float = 0.04, kind: str = "call") -> float:
    if T_years <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        intrinsic = (S - K) if kind == "call" else (K - S)
        return max(0.0, intrinsic)
    sqrtT = math.sqrt(T_years)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T_years) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    if kind == "call":
        return S * norm_cdf(d1) - K * math.exp(-r * T_years) * norm_cdf(d2)
    return K * math.exp(-r * T_years) * norm_cdf(-d2) - S * norm_cdf(-d1)


@dataclass
class BTParams:
    stop_pct: float = 0.35
    target_pct: float = 0.60
    max_hold_days: int = 15
    dte_days: int = 30
    iv_multiplier: float = 1.15
    risk_per_trade: float = 0.01
    warmup: int = 120
    start_equity: float = 100_000.0


@dataclass
class OpenTrade:
    direction: str
    entry_index: int
    entry_price_underlying: float
    strike: float
    premium_entry: float
    iv: float
    qty: int
    days_held: int = 0


@dataclass
class SymbolResult:
    symbol: str
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)


def synthetic_daily_bars(symbol: str, days: int) -> pd.DataFrame:
    seed = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    n = min(days, 1500)
    drift = rng.uniform(-0.0004, 0.0012)
    vol = rng.uniform(0.012, 0.03)
    steps = rng.normal(drift, vol, n)
    close = 100 * np.exp(np.cumsum(steps))
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    times = pd.date_range(end=end, periods=n, freq="1D")
    return pd.DataFrame(
        {"time": times, "open": open_, "high": high, "low": low, "close": close,
         "volume": rng.integers(5e5, 5e6, n)}
    )


def load_daily_bars(symbol: str, days: int, offline: bool):
    if not offline:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.environ.get("ALPACA_API_KEY", "")
            secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
            if api_key and secret_key:
                from broker.alpaca_client import AlpacaBroker

                broker = AlpacaBroker(api_key, secret_key)
                bars = broker.get_stock_bars(symbol, timeframe="1Day", days=days)
                if bars is not None and len(bars) >= 200:
                    print(f"  {symbol}: loaded {len(bars)} daily bars from Alpaca")
                    return bars
        except Exception as exc:
            print(f"  {symbol}: Alpaca unavailable ({exc}); using synthetic data")

    bars = synthetic_daily_bars(symbol, days)
    print(f"  {symbol}: generated {len(bars)} synthetic daily bars")
    return bars


def realized_vol(close: pd.Series, window: int = 20) -> float:
    rets = np.log(close / close.shift(1)).dropna().tail(window)
    if len(rets) < 5:
        return 0.25
    return float(rets.std() * math.sqrt(252))


def signal_on_close(window: pd.DataFrame):
    macd, sig, _ = calculate_macd(window)
    cross = None
    if len(macd) >= 2:
        prev_diff = macd.iloc[-2] - sig.iloc[-2]
        curr_diff = macd.iloc[-1] - sig.iloc[-1]
        if prev_diff <= 0 < curr_diff:
            cross = "bullish"
        elif prev_diff >= 0 > curr_diff:
            cross = "bearish"

    if cross is None:
        return None

    ema_df = calculate_ema(window, periods=(20,))
    above = ema_df["close"].iloc[-1] > ema_df["EMA_20"].iloc[-1]
    rsi_series = calculate_rsi(window)
    rsi = float(rsi_series.iloc[-1])

    if cross == "bullish" and above and rsi < 72:
        return "bullish"
    if cross == "bearish" and not above and rsi > 28:
        return "bearish"
    return None


def simulate_symbol(symbol: str, bars: pd.DataFrame, params: BTParams) -> SymbolResult:
    result = SymbolResult(symbol=symbol)
    equity = params.start_equity
    open_trade = None
    closes = bars["close"].reset_index(drop=True)

    for i in range(params.warmup, len(bars)):
        price = float(closes.iloc[i])
        window = bars.iloc[max(0, i - 300): i]

        if open_trade is not None:
            open_trade.days_held += 1
            t_years = max((params.dte_days - open_trade.days_held), 0.5) / 365.0
            premium_now = bs_price(price, open_trade.strike, t_years, open_trade.iv,
                                   kind="call" if open_trade.direction == "bullish" else "put")
            pnl_pct = premium_now / open_trade.premium_entry - 1
            exit_reason = None
            if pnl_pct <= -params.stop_pct:
                exit_reason = "stop"
            elif pnl_pct >= params.target_pct:
                exit_reason = "target"
            elif open_trade.days_held >= params.max_hold_days:
                exit_reason = "time"
            else:
                fresh_signal = signal_on_close(window)
                if fresh_signal is not None and fresh_signal != open_trade.direction:
                    exit_reason = "flip"

            if exit_reason:
                cost = open_trade.premium_entry * 100 * open_trade.qty
                proceeds = premium_now * 100 * open_trade.qty
                equity += proceeds - cost
                result.trades.append(
                    {
                        "symbol": symbol,
                        "direction": open_trade.direction,
                        "entry_i": open_trade.entry_index,
                        "exit_i": i,
                        "days": open_trade.days_held,
                        "premium_entry": round(open_trade.premium_entry, 3),
                        "premium_exit": round(premium_now, 3),
                        "pnl_usd": round(proceeds - cost, 2),
                        "return_pct": round(pnl_pct * 100, 2),
                        "exit": exit_reason,
                    }
                )
                open_trade = None

        if open_trade is None:
            signal = signal_on_close(window)
            if signal is not None:
                rv = realized_vol(window["close"])
                iv = max(rv * params.iv_multiplier, 0.10)
                strike = round(price)
                t_years = params.dte_days / 365.0
                premium = bs_price(price, strike, t_years, iv,
                                   kind="call" if signal == "bullish" else "put")
                premium = max(premium, price * 0.004)
                risk_budget = equity * params.risk_per_trade
                qty = max(1, int(risk_budget // (premium * 100)))
                open_trade = OpenTrade(
                    direction=signal,
                    entry_index=i,
                    entry_price_underlying=price,
                    strike=strike,
                    premium_entry=premium,
                    iv=iv,
                    qty=qty,
                )

        result.equity_curve.append({"index": i, "equity": round(equity, 2)})

    return result


def summarize(results, params: BTParams):
    rows = []
    final_equities = []
    for res in results:
        trades_df = pd.DataFrame(res.trades)
        wins = trades_df[trades_df["pnl_usd"] > 0] if not trades_df.empty else []
        losses = trades_df[trades_df["pnl_usd"] <= 0] if not trades_df.empty else []
        gross_win = wins["pnl_usd"].sum() if not wins.empty else 0.0
        gross_loss = abs(losses["pnl_usd"].sum()) if not losses.empty else 0.0
        curve = pd.Series([e["equity"] for e in res.equity_curve])
        peak = curve.cummax()
        dd = ((curve / peak) - 1).min() if len(curve) else 0.0
        final_equities.append(curve.iloc[-1] if len(curve) else params.start_equity)

        rows.append(
            {
                "symbol": res.symbol,
                "trades": len(trades_df),
                "win_rate_%": round(len(wins) / len(trades_df) * 100, 1) if len(trades_df) else 0.0,
                "pnl_usd": round((final_equities[-1] - params.start_equity), 2),
                "return_%": round((final_equities[-1] / params.start_equity - 1) * 100, 2),
                "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
                "max_dd_%": round(dd * 100, 2),
            }
        )
    return pd.DataFrame(rows), sum(final_equities)


def save_outputs(results, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    all_trades = []
    for res in results:
        all_trades.extend(res.trades)
    if all_trades:
        pd.DataFrame(all_trades).to_csv(os.path.join(out_dir, "trades.csv"), index=False)
    equity_rows = []
    for res in results:
        for point in res.equity_curve:
            equity_rows.append({"symbol": res.symbol, **point})
    pd.DataFrame(equity_rows).to_csv(os.path.join(out_dir, "equity.csv"), index=False)


def main():
    parser = argparse.ArgumentParser(description="Council signal backtester with Black-Scholes option P&L")
    parser.add_argument("--symbols", default=None, help="comma-separated; defaults to symbols.txt")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--offline", action="store_true", help="skip Alpaca even if keys exist")
    parser.add_argument("--stop", type=float, default=0.35)
    parser.add_argument("--target", type=float, default=0.60)
    parser.add_argument("--risk", type=float, default=0.01)
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = []
        symbols_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "symbols.txt")
        try:
            with open(symbols_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    token = line.split("#")[0].strip().upper()
                    if token and token not in symbols:
                        symbols.append(token)
        except OSError:
            pass
        symbols = symbols or ["AAPL", "MSFT", "NVDA", "SPY", "TSLA"]
    params = BTParams(stop_pct=args.stop, target_pct=args.target, risk_per_trade=args.risk)

    print(f"Backtesting {len(symbols)} symbols over ~{args.days} days "
          f"(stop={args.stop:.0%}, target={args.target:.0%}, risk/trade={args.risk:.1%})")

    results = []
    for symbol in symbols:
        bars = load_daily_bars(symbol, args.days, args.offline)
        results.append(simulate_symbol(symbol, bars, params))

    summary, total_final = summarize(results, params)
    print("\n=== Per-symbol results ===")
    print(summary.to_string(index=False))
    portfolio_return = total_final / (params.start_equity * len(symbols)) - 1
    print(f"\nPortfolio (equal-weight): ${total_final:,.2f} | return {portfolio_return:+.2%}")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    save_outputs(results, out_dir)
    print(f"Saved trades.csv and equity.csv to {out_dir}")


if __name__ == "__main__":
    main()
