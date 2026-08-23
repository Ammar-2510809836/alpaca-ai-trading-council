import logging
import math

from agent.brains.base import Brain
from agent.models import TradeProposal

SYSTEM_PROMPT = """You are the Options Strategist brain inside an autonomous trading council.
The council has reached a directional consensus on an underlying stock. You receive the option chain
snapshot (strikes, DTE, IV, delta, bid/ask). Design ONE concrete structure.

Respond ONLY with JSON:
{"structure": "long_call" | "long_put" | "bull_call_spread" | "bear_put_spread",
 "buy_occ": "OCC symbol to buy (empty if none)",
 "sell_occ": "OCC symbol to sell for spreads (empty otherwise)",
 "rationale": "2-3 sentences on why this strike/expiry and structure"}

Guidelines:
- Prefer 20-45 DTE. Long options: delta around 0.40-0.55. Spread short leg: delta around 0.15-0.30.
- Use verticals when IV is elevated; naked longs when IV is low relative to the chain's average.
- Never invent OCC symbols; only use ones from the provided chain.
- If no sensible contract exists, return {"structure": "none", ...}."""


class OptionsStrategist(Brain):
    name = "options-strategist"
    weight = 1.2

    def decide(self, symbol: str, context: dict) -> TradeProposal | None:
        direction = context.get("council_direction")
        if direction not in ("bullish", "bearish"):
            return None

        chain = context.get("option_chain")
        if chain is None and self.tools is not None:
            cfg = self.config.get("options", {})
            chain = self.tools.option_chain(
                symbol,
                limit=200,
                min_dte=cfg.get("min_dte", 7),
                max_dte=cfg.get("max_dte", 45),
            )
            context["option_chain"] = chain

        if not chain:
            logging.info(f"[{self.name}] empty option chain for {symbol}")
            return None

        price = context.get("price") or 0
        parsed = None
        if self.llm and self.llm.enabled:
            prompt = (
                f"Underlying: {symbol} at ${price:.2f}\n"
                f"Council direction: {direction.upper()}\n\n"
                f"Chain snapshot ({len(chain)} contracts):\n"
                + self._format_chain(chain)
                + "\nDesign the structure as JSON."
            )
            parsed = self.llm.complete_json(SYSTEM_PROMPT, prompt)

        proposal = self._build_from_llm(parsed, symbol, context) or self._build_rule_based(
            direction, symbol, context
        )
        return proposal

    @staticmethod
    def _format_chain(chain) -> str:
        lines = []
        for c in chain[:60]:
            mid = (c.get("bid", 0) + c.get("ask", 0)) / 2
            lines.append(
                f"{c['occ_symbol']} dte={c.get('dte')} type={c.get('type')} k={c.get('strike')} "
                f"mid={mid:.2f} iv={c.get('iv', 0):.2f} delta={c.get('delta', 0):.2f}"
            )
        return "\n".join(lines)

    def _build_from_llm(self, parsed, symbol, context) -> TradeProposal | None:
        if not parsed:
            return None

        structure = str(parsed.get("structure", "none")).lower()
        valid = ("long_call", "long_put", "bull_call_spread", "bear_put_spread")
        if structure not in valid:
            return None

        buy_occ = str(parsed.get("buy_occ", "")).upper()
        sell_occ = str(parsed.get("sell_occ", "")).upper()
        chain_by_occ = {c["occ_symbol"]: c for c in context.get("option_chain", [])}

        if buy_occ not in chain_by_occ:
            return None
        if "spread" in structure and sell_occ not in chain_by_occ:
            return None

        legs = [{"action": "buy", "occ_symbol": buy_occ, "ratio": 1}]
        if "spread" in structure:
            legs.append({"action": "sell", "occ_symbol": sell_occ, "ratio": 1})

        proposal = self._price_proposal(structure, symbol, legs, context)
        if proposal:
            proposal.rationale = str(parsed.get("rationale", ""))[:500]
        return proposal

    def _build_rule_based(self, direction, symbol, context) -> TradeProposal | None:
        chain = context.get("option_chain") or []
        price = float(context.get("price") or 0)
        calls = [c for c in chain if c["type"] == "call"]
        puts = [c for c in chain if c["type"] == "put"]

        if not calls or not puts:
            return None

        pool = calls if direction == "bullish" else puts
        with_greeks = [c for c in pool if abs(c.get("delta", 0)) > 0.01]

        if with_greeks:
            long_leg = min(with_greeks, key=lambda c: abs(abs(c.get("delta", 0)) - 0.45))
        elif price:
            long_leg = min(pool, key=lambda c: abs(c["strike"] - price))
        else:
            return None

        expiry = long_leg["expiry"]
        same_expiry = [c for c in pool if c["expiry"] == expiry]

        quoted = [c for c in chain if c.get("iv", 0) > 0]
        avg_iv = sum(c["iv"] for c in quoted) / max(len(quoted), 1)
        use_spread = avg_iv > self.config.get("options", {}).get("high_iv_threshold", 0.45)

        legs = [{"action": "buy", "occ_symbol": long_leg["occ_symbol"], "ratio": 1}]
        structure = "long_call" if direction == "bullish" else "long_put"

        if use_spread and len(same_expiry) >= 2:
            short_target = -0.25 if direction == "bearish" else 0.25
            short_pool = [
                c
                for c in same_expiry
                if c["occ_symbol"] != long_leg["occ_symbol"]
                and abs(c.get("delta", 0)) > 0.01
                and (
                    (direction == "bullish" and c["strike"] > long_leg["strike"])
                    or (direction == "bearish" and c["strike"] < long_leg["strike"])
                )
            ]
            if short_pool:
                short_leg = min(short_pool, key=lambda c: abs(c.get("delta", 0) - short_target))
                legs.append({"action": "sell", "occ_symbol": short_leg["occ_symbol"], "ratio": 1})
                structure = "bull_call_spread" if direction == "bullish" else "bear_put_spread"

        proposal = self._price_proposal(structure, symbol, legs, context)
        if proposal:
            proposal.rationale = (
                f"Rule-based selection: {long_leg['occ_symbol']} "
                f"(delta {long_leg.get('delta', 0):.2f}), chain avg IV {avg_iv:.2f}, "
                + ("vertical chosen due to elevated IV" if len(legs) > 1 else "naked long chosen, IV not elevated")
            )
        return proposal

    def _price_proposal(self, structure, symbol, legs, context) -> TradeProposal | None:
        chain_by_occ = {c["occ_symbol"]: c for c in context.get("option_chain", [])}
        priced = []
        for leg in legs:
            contract = chain_by_occ.get(leg["occ_symbol"])
            if not contract:
                return None
            bid, ask = contract.get("bid", 0), contract.get("ask", 0)
            if bid <= 0 and ask <= 0:
                return None
            leg = dict(leg)
            leg["mid"] = round((bid + ask) / 2 or ask or bid, 2)
            leg["contract"] = contract
            priced.append(leg)

        net_debit = sum(l["mid"] * l["ratio"] for l in priced if l["action"] == "buy")
        net_credit_in = sum(l["mid"] * l["ratio"] for l in priced if l["action"] == "sell")

        proposal = TradeProposal(
            underlying=symbol,
            asset_class="option",
            direction="bullish" if "bull" in structure or "call" in structure else "bearish",
            structure=structure,
            legs=[{k: v for k, v in l.items() if k != "contract"} for l in priced],
        )

        if "spread" in structure:
            strikes = sorted(l["contract"]["strike"] for l in priced)
            width = abs(strikes[-1] - strikes[-2])
            proposal.max_debit = round(net_debit - net_credit_in, 2)
            proposal.max_loss = round(proposal.max_debit, 2)
            proposal.max_profit = round(max(width - proposal.max_debit, 0), 2)
            proposal.limit_price = proposal.max_debit
            if proposal.max_debit < 0.05 or width < 1:
                logging.info(
                    f"[options-strategist] rejecting degenerate spread: "
                    f"debit={proposal.max_debit} width={width}"
                )
                return None
        else:
            premium = round(net_debit, 2)
            if premium < 0.10:
                logging.info(f"[options-strategist] rejecting degenerate premium: {premium}")
                return None
            proposal.max_debit = premium
            proposal.max_loss = premium
            proposal.limit_price = premium

        return proposal
