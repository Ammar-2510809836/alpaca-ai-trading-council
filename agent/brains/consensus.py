import logging

from agent.models import CouncilDecision


class Council:
    def __init__(self, analyst, news_brain, strategist, risk_governor, config=None):
        self.analyst = analyst
        self.news = news_brain
        self.strategist = strategist
        self.risk = risk_governor
        self.config = config or {}

    def _spot_proposal(self, symbol, direction, context):
        from agent.models import TradeProposal

        if direction != "bullish":
            return None

        account = context.get("account") or {}
        equity = float(account.get("equity", 0) or 0)
        price = float(context.get("price") or 0)
        if equity <= 0 or price <= 0:
            return None

        budget_pct = float(
            (self.config.get("crypto") or {}).get("quote_allocation_pct", 0.02)
        )
        notional = round(equity * budget_pct, 2)
        qty = round(notional / price, 6)
        if qty <= 0:
            return None

        return TradeProposal(
            underlying=symbol,
            asset_class="crypto",
            direction="bullish",
            structure="long_spot",
            qty=qty,
            max_debit=notional,
            rationale=(
                f"24/7 spot crypto: council consensus bullish, allocating "
                f"{budget_pct:.1%} of equity ({notional:.2f} USD) at {price:.2f}"
            ),
        )

    def run(self, symbol: str, context: dict) -> CouncilDecision:
        votes = [self.analyst.decide(symbol, context), self.news.decide(symbol, context)]

        weights = {
            "technical-analyst": getattr(self.analyst, "weight", 1.0),
            "news-sentiment": getattr(self.news, "weight", 1.0),
        }

        score = 0.0
        for vote in votes:
            sign = {"bullish": 1, "bearish": -1}.get(vote.direction, 0)
            score += sign * vote.confidence * weights.get(vote.brain, 1.0)

        threshold = float(self.config.get("council", {}).get("consensus_threshold", 0.45))
        direction = "neutral"
        if score >= threshold:
            direction = "bullish"
        elif score <= -threshold:
            direction = "bearish"

        decision = CouncilDecision(
            symbol=symbol,
            action="hold",
            confidence=abs(score),
            votes=votes,
            summary=f"Directional score {score:+.2f} vs threshold {threshold:.2f}",
        )

        if direction == "neutral":
            decision.summary += " -> no consensus, holding"
            return decision

        if context.get("spot"):
            proposal = self._spot_proposal(symbol, direction, context)
            if proposal is None:
                decision.summary += (
                    f" -> {direction} bias in 24/7 spot mode"
                    + (" (long-only, skipping)" if direction == "bearish" else " (no budget)")
                    + ", holding"
                )
                return decision
            decision.action = "buy_option_structure" if proposal.asset_class == "option" else "buy_spot_crypto"
            decision.proposal = proposal
            decision.summary += f" -> {direction} via {proposal.structure}"

            veto_reason = self.risk.veto(decision, context)
            if veto_reason:
                decision.action = "hold"
                decision.vetoed_by = "risk-governor"
                decision.veto_reason = veto_reason
                decision.summary += f" -> VETOED by risk governor: {veto_reason}"
            else:
                decision.summary += " -> approved"

            return decision

        context["council_direction"] = direction
        proposal = self.strategist.decide(symbol, context)
        if proposal is None:
            decision.summary += f" -> {direction} bias but no viable options structure, holding"
            return decision

        decision.action = "buy_option_structure"
        decision.proposal = proposal
        decision.summary += f" -> {direction} via {proposal.structure}"

        veto_reason = self.risk.veto(decision, context)
        if veto_reason:
            decision.action = "hold"
            decision.vetoed_by = "risk-governor"
            decision.veto_reason = veto_reason
            decision.summary += f" -> VETOED by risk governor: {veto_reason}"
        else:
            decision.summary += " -> approved"

        return decision
