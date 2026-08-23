import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.enums import DataFeed
from alpaca.data.requests import (
    CryptoBarsRequest,
    NewsRequest,
    OptionChainRequest,
    StockBarsRequest,
    StockLatestQuoteRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    OptionLegRequest,
    StopLossRequest,
    TakeProfitRequest,
)

TIMEFRAMES = {
    "1Min": TimeFrame(1, TimeFrameUnit.Minute),
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "30Min": TimeFrame(30, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1Day": TimeFrame(1, TimeFrameUnit.Day),
}

TIMEFRAME_MINUTES = {
    "1Min": 1,
    "5Min": 5,
    "15Min": 15,
    "30Min": 30,
    "1Hour": 60,
    "1Day": 1440,
}


def parse_occ_symbol(symbol: str):
    m = re.match(r"^([A-Z]+)(\d{6})([CP])(\d{8})$", symbol.upper())
    if not m:
        return None
    root, date_part, cp, strike_part = m.groups()
    expiry = datetime.strptime(date_part, "%y%m%d").date()
    strike = int(strike_part) / 1000.0
    return {
        "underlying": root,
        "expiry": expiry.isoformat(),
        "type": "call" if cp == "C" else "put",
        "strike": strike,
    }


def _field(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, default)
    return value


class AlpacaBroker:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        paper: bool = True,
        data_feed: str = "iex",
        order_tag: str = "aiagent",
    ):
        self.paper = paper
        self.order_tag = order_tag
        self.trading = TradingClient(api_key, secret_key, paper=paper)
        self.stock_data = StockHistoricalDataClient(api_key, secret_key)
        self.data_feed = DataFeed.IEX if data_feed.lower() == "iex" else DataFeed.SIP
        self.option_data = OptionHistoricalDataClient(api_key, secret_key)
        self.crypto_data = CryptoHistoricalDataClient(api_key, secret_key)
        self.news_client = NewsClient(api_key, secret_key)

    def _tag(self, label: str) -> str:
        return f"{self.order_tag}-{label}-{uuid.uuid4().hex[:8]}"

    def get_clock(self) -> Optional[dict]:
        try:
            clock = self.trading.get_clock()
            return {
                "is_open": clock.is_open,
                "next_open": str(clock.next_open),
                "next_close": str(clock.next_close),
                "timestamp": str(clock.timestamp),
            }
        except Exception as exc:
            logging.error(f"get_clock failed: {exc}")
            return None

    def get_account(self) -> Optional[dict]:
        try:
            acct = self.trading.get_account()
            return {
                "equity": float(acct.equity),
                "cash": float(acct.cash),
                "buying_power": float(acct.buying_power),
                "portfolio_value": float(acct.portfolio_value),
                "paper": self.paper,
            }
        except Exception as exc:
            logging.error(f"get_account failed: {exc}")
            return None

    def get_positions(self) -> list:
        try:
            raw = self.trading.get_all_positions()
        except Exception as exc:
            logging.error(f"get_positions failed: {exc}")
            return []

        positions = []
        for p in raw:
            asset_class = str(_field(p, "asset_class", ""))
            underlying = _field(p, "underlying_symbol")
            positions.append(
                {
                    "symbol": p.symbol,
                    "qty": abs(float(p.qty)),
                    "side": "long" if float(p.qty) > 0 else "short",
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price or 0),
                    "unrealized_pl": float(p.unrealized_pl or 0),
                    "asset_class": "option" if "option" in asset_class
                    else ("crypto" if "crypto" in asset_class else "stock"),
                    "underlying": underlying or parse_occ_symbol(p.symbol)["underlying"]
                    if "option" in asset_class and parse_occ_symbol(p.symbol)
                    else p.symbol,
                    "change_today": float(getattr(p, "change_today", 0) or 0),
                }
            )
        return positions

    def get_portfolio_history(self, days: int = 30) -> list:
        try:
            from alpaca.trading.requests import GetPortfolioHistoryRequest

            period_map = {7: "1W", 14: "2W", 30: "1M", 90: "3M"}
            history_filter = GetPortfolioHistoryRequest(
                period=period_map.get(days, "1M"),
                timeframe="1D",
            )
            history = self.trading.get_portfolio_history(history_filter=history_filter)
            equity = history.equity or []
            timestamps = history.timestamp or []
            return [
                {"timestamp": int(ts), "equity": float(eq)}
                for ts, eq in zip(timestamps, equity)
            ]
        except Exception as exc:
            logging.error(f"get_portfolio_history failed: {exc}")
            return []

    def get_stock_bars(self, symbol: str, timeframe: str = "15Min", days: int = 10) -> pd.DataFrame:
        tf = TIMEFRAMES.get(timeframe, TIMEFRAMES["15Min"])
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        try:
            response = self.stock_data.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=tf,
                    start=start,
                    end=end,
                    feed=self.data_feed,
                )
            )
        except Exception as exc:
            logging.error(f"get_stock_bars({symbol}) failed: {exc}")
            return pd.DataFrame()

        bars = getattr(response, "df", None)
        if bars is None or bars.empty:
            return pd.DataFrame()

        if isinstance(bars.index, pd.MultiIndex):
            bars = bars.xs(symbol, level="symbol")

        df = bars.reset_index()
        df.columns = [str(c).lower() for c in df.columns]
        rename = {"timestamp": "time"}
        df = df.rename(columns=rename)
        keep = [c for c in ("time", "open", "high", "low", "close", "volume") if c in df.columns]
        df = df[keep].dropna(subset=["close"]).reset_index(drop=True)

        drop_last = TIMEFRAME_MINUTES.get(timeframe, 15)
        if not df.empty and len(df) > 1:
            last_time = pd.to_datetime(df["time"].iloc[-1])
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last_time.to_pydatetime()).total_seconds() < drop_last * 60:
                df = df.iloc[:-1]

        return df.reset_index(drop=True)

    def get_crypto_bars(self, symbol: str, timeframe: str = "15Min", days: int = 10) -> pd.DataFrame:
        tf = TIMEFRAMES.get(timeframe, TIMEFRAMES["15Min"])
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        try:
            response = self.crypto_data.get_crypto_bars(
                CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end)
            )
        except Exception as exc:
            logging.error(f"get_crypto_bars({symbol}) failed: {exc}")
            return pd.DataFrame()

        bars = getattr(response, "df", None)
        if bars is None or bars.empty:
            return pd.DataFrame()

        if isinstance(bars.index, pd.MultiIndex):
            try:
                bars = bars.xs(symbol, level="symbol")
            except KeyError:
                bars = bars.droplevel(0)

        df = bars.reset_index()
        df.columns = [str(c).lower() for c in df.columns]
        df = df.rename(columns={"timestamp": "time"})
        keep = [c for c in ("time", "open", "high", "low", "close", "volume") if c in df.columns]
        df = df[keep].dropna(subset=["close"]).reset_index(drop=True)

        drop_last = TIMEFRAME_MINUTES.get(timeframe, 15)
        if not df.empty and len(df) > 1:
            last_time = pd.to_datetime(df["time"].iloc[-1])
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last_time.to_pydatetime()).total_seconds() < drop_last * 60:
                df = df.iloc[:-1]

        return df.reset_index(drop=True)

    def submit_crypto_order(self, symbol: str, side: str, qty: float, label: str) -> Optional[dict]:
        request = MarketOrderRequest(
            symbol=symbol,
            qty=str(round(float(qty), 6)),
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.GTC,
            client_order_id=self._tag(label),
        )
        try:
            order = self.trading.submit_order(request)
            return {"order_id": order.id, "client_order_id": order.client_order_id}
        except Exception as exc:
            logging.error(f"submit_crypto_order({symbol}) failed: {exc}")
            return None

    def get_latest_price(self, symbol: str) -> Optional[float]:
        try:
            snap = self.stock_data.get_stock_latest_quote(
                StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=self.data_feed)
            )
            quote = snap[symbol]
            bid, ask = _field(quote, "bid_price"), _field(quote, "ask_price")
            if bid and ask and ask >= bid > 0:
                return round((float(bid) + float(ask)) / 2, 2)

            one_sided = float(bid or ask or 0)
            if one_sided > 0:
                logging.info(f"one-sided IEX quote for {symbol}, using {one_sided}")
                return round(one_sided, 2)

            trade = getattr(quote, "trade_price", None) or _field(quote, "last_trade", {}).get("price")
            if trade:
                return round(float(trade), 2)
        except Exception as exc:
            logging.warning(f"get_latest_price({symbol}) quote failed: {exc}")

        try:
            bars = self.get_stock_bars(symbol, timeframe="1Day", days=5)
            if bars is not None and not bars.empty:
                close = float(bars["close"].iloc[-1])
                logging.info(f"{symbol}: using last daily close {close} as reference price")
                return round(close, 2)
        except Exception as exc:
            logging.error(f"get_latest_price({symbol}) bar fallback failed: {exc}")

        return None

    def get_option_chain(self, underlying: str, min_dte: int = 7, max_dte: int = 45) -> list:
        try:
            response = self.option_data.get_option_chain(
                OptionChainRequest(underlying_symbol=underlying.upper())
            )
        except Exception as exc:
            logging.error(f"get_option_chain({underlying}) failed: {exc}")
            return []

        pairs = []
        df = getattr(response, "df", None)
        if df is not None and hasattr(df, "iterrows"):
            for idx, row in df.iterrows():
                sym = str(_field(row, "symbol", idx) or idx).upper()
                pairs.append((sym, row))
        elif isinstance(response, dict):
            for key, value in response.items():
                sym = str(_field(value, "symbol", key) or key).upper()
                pairs.append((sym, value))

        if not pairs:
            return []

        today = datetime.now(timezone.utc).date()
        contracts = []
        for occ, row in pairs:
            occ = occ.upper()
            parsed = parse_occ_symbol(occ)
            if not parsed:
                continue
            dte = (datetime.strptime(parsed["expiry"], "%Y-%m-%d").date() - today).days
            if dte < min_dte or dte > max_dte:
                continue

            greeks = _field(row, "greeks") or {}
            quote = _field(row, "latest_quote") or {}
            contracts.append(
                {
                    "occ_symbol": occ,
                    "dte": dte,
                    "bid": float(_field(quote, "bid_price") or 0),
                    "ask": float(_field(quote, "ask_price") or 0),
                    "iv": float(_field(row, "implied_volatility") or 0),
                    "delta": float(_field(greeks, "delta") or 0),
                    "gamma": float(_field(greeks, "gamma") or 0),
                    "theta": float(_field(greeks, "theta") or 0),
                    "vega": float(_field(greeks, "vega") or 0),
                    **parsed,
                }
            )

        contracts.sort(key=lambda c: (c["expiry"], c["strike"]))
        return contracts

    def get_news(self, symbols: str, limit: int = 6, lookback_days: int = 3) -> list:
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=lookback_days)
            items = self.news_client.get_news(
                NewsRequest(symbols=symbols, limit=limit, start=start, end=end)
            )
            raw = getattr(items, "data", None)
            if isinstance(raw, dict):
                raw = raw.get("news", [])
            news = []
            for item in (raw or [])[:limit]:
                news.append(
                    {
                        "headline": item.headline,
                        "summary": (item.summary or "")[:400],
                        "source": item.source,
                        "created_at": str(item.created_at),
                    }
                )
            return news
        except Exception as exc:
            logging.error(f"get_news({symbols}) failed: {exc}")
            return []

    def submit_bracket_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        take_profit_pct: float,
        stop_loss_pct: float,
        label: str,
    ) -> Optional[dict]:
        entry = self.get_latest_price(symbol)
        if entry is None:
            logging.warning(f"No price for {symbol}, cannot build bracket")
            return None

        direction = 1 if side == "buy" else -1
        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(entry * (1 + direction * take_profit_pct), 2)),
            stop_loss=StopLossRequest(stop_price=round(entry * (1 - direction * stop_loss_pct), 2)),
            client_order_id=self._tag(label),
        )

        try:
            order = self.trading.submit_order(request)
            return {"order_id": order.id, "client_order_id": order.client_order_id, "entry_estimate": entry}
        except Exception as exc:
            logging.error(f"submit_bracket_order({symbol}) failed: {exc}")
            return None

    def submit_option_limit_order(self, occ_symbol: str, side: str, qty: int, limit_price: float, label: str) -> Optional[dict]:
        request = LimitOrderRequest(
            symbol=occ_symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
            client_order_id=self._tag(label),
        )
        try:
            order = self.trading.submit_order(request)
            return {"order_id": order.id, "client_order_id": order.client_order_id}
        except Exception as exc:
            logging.error(f"submit_option_limit_order({occ_symbol}) failed: {exc}")
            return None

    def submit_option_spread(
        self,
        legs: list,
        qty: int,
        limit_price: float,
        label: str,
    ) -> Optional[dict]:
        leg_requests = []
        has_buy = False
        for leg in legs:
            side = OrderSide.BUY if leg["action"] == "buy" else OrderSide.SELL
            has_buy = has_buy or leg["action"] == "buy"
            leg_requests.append(
                OptionLegRequest(
                    symbol=leg["occ_symbol"],
                    ratio_qty=float(leg.get("ratio", 1)),
                    side=side,
                )
            )

        request = LimitOrderRequest(
            qty=qty,
            side=OrderSide.BUY if has_buy else OrderSide.SELL,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.MLEG,
            limit_price=round(max(float(limit_price or 0), 0.01), 2),
            legs=leg_requests,
            client_order_id=self._tag(label),
        )

        try:
            order = self.trading.submit_order(request)
            return {"order_id": order.id, "client_order_id": order.client_order_id}
        except Exception as exc:
            logging.error(f"submit_option_spread failed: {exc}")
            return None

    def get_open_orders(self) -> list:
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus

            raw = self.trading.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True)
            )
        except Exception as exc:
            logging.error(f"get_open_orders failed: {exc}")
            return []

        symbols = []
        for o in raw:
            symbols.append(str(o.symbol or "").upper())
            for leg in getattr(o, "legs", None) or []:
                leg_sym = getattr(leg, "symbol", None) or (leg.get("symbol") if isinstance(leg, dict) else None)
                if leg_sym:
                    symbols.append(str(leg_sym).upper())
        return [s for s in symbols if s]

    def close_position(self, symbol: str) -> bool:
        try:
            self.trading.close_position(symbol)
            return True
        except Exception as exc:
            logging.error(f"close_position({symbol}) failed: {exc}")
            return False

    def close_all_positions(self) -> int:
        closed = 0
        for position in self.get_positions():
            if self.close_position(position["symbol"]):
                closed += 1
        return closed
