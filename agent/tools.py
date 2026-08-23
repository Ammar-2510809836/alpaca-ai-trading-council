import json
import logging
import time

HEADLINE_CACHE_TTL = 600


def _parse_tool_payload(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


class AgentTools:
    def __init__(self, broker, mcp_bridge=None):
        self.broker = broker
        self.mcp = mcp_bridge
        self._news_cache = {}

    def news(self, symbol: str, limit: int = 6) -> list:
        cached = self._news_cache.get(symbol.upper())
        if cached and time.time() - cached[0] < HEADLINE_CACHE_TTL:
            return cached[1]

        items = []
        if self.mcp and self.mcp.available:
            payload = _parse_tool_payload(
                self.mcp.call_tool("get_news", {"symbols": symbol.upper(), "limit": limit})
            )
            if isinstance(payload, list) and payload:
                items = payload[:limit]

        if not items:
            items = self.broker.get_news(symbol, limit=limit)

        self._news_cache[symbol.upper()] = (time.time(), items)
        return items

    def option_chain(self, underlying: str, limit: int = 200, min_dte: int = 7, max_dte: int = 45) -> list:
        if self.mcp and self.mcp.available:
            payload = _parse_tool_payload(
                self.mcp.call_tool(
                    "get_option_chain",
                    {"underlying_asset": underlying.upper()},
                )
            )
            normalized = _normalize_mcp_chain(payload)
            if normalized:
                return normalized[:limit]

        return self.broker.get_option_chain(underlying, min_dte=min_dte, max_dte=max_dte)

    def account(self):
        if self.mcp and self.mcp.available:
            payload = _parse_tool_payload(self.mcp.call_tool("get_account_info", {}))
            if isinstance(payload, dict) and payload:
                equity = payload.get("equity") or payload.get("portfolio_value")
                if equity:
                    return {
                        "equity": float(str(equity).replace("$", "").replace(",", "") or 0),
                        "cash": float(str(payload.get("cash", 0)).replace("$", "").replace(",", "") or 0),
                        "buying_power": float(
                            str(payload.get("buying_power", 0)).replace("$", "").replace(",", "") or 0
                        ),
                        "via_mcp": True,
                    }

        return self.broker.get_account()

    def mode_label(self) -> str:
        return "Alpaca MCP Server" if (self.mcp and self.mcp.available) else "Alpaca REST API"


def _normalize_mcp_chain(payload) -> list:
    rows = None
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in ("contracts", "snapshots", "chain", "option_chain"):
            inner = payload.get(key)
            if isinstance(inner, list):
                rows = inner
                break
        if rows is None:
            single = payload.get("occ_symbol") or payload.get("symbol")
            if single:
                rows = [payload]

    if not rows:
        return []

    normalized = []
    today_key = {"expiry", "expiration_date", "expiration"}
    for row in rows:
        if not isinstance(row, dict):
            continue
        occ = str(row.get("occ_symbol") or row.get("symbol") or "").upper()
        if not occ:
            continue
        expiry = next((row[k] for k in today_key if row.get(k)), "")
        greeks = row.get("greeks") or {}
        quote = row.get("latest_quote") or {}
        try:
            occ_type = str(row.get("type") or "").lower()
            if occ_type not in ("call", "put"):
                cp = occ[-9].upper() if len(occ) >= 15 else ""
                occ_type = {"C": "call", "P": "put"}.get(cp, "")
            normalized.append(
                {
                    "occ_symbol": occ,
                    "underlying": str(row.get("underlying_asset") or row.get("underlying") or "").upper(),
                    "type": occ_type,
                    "strike": float(row.get("strike_price") or row.get("strike") or 0),
                    "dte": int(row.get("dte") or 0),
                    "expiry": str(expiry),
                    "bid": float(quote.get("bid_price", row.get("bid", 0)) or 0),
                    "ask": float(quote.get("ask_price", row.get("ask", 0)) or 0),
                    "iv": float(row.get("implied_volatility", row.get("iv", 0)) or 0),
                    "delta": float(greeks.get("delta", row.get("delta", 0)) or 0),
                    "gamma": float(greeks.get("gamma", row.get("gamma", 0)) or 0),
                    "theta": float(greeks.get("theta", row.get("theta", 0)) or 0),
                    "vega": float(greeks.get("vega", row.get("vega", 0)) or 0),
                }
            )
        except (TypeError, ValueError):
            continue

    return [r for r in normalized if r["type"] in ("call", "put")]
