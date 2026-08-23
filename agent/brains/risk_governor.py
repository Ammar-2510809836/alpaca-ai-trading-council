import logging
from datetime import datetime, timezone

from agent.brains.base import Brain


class RiskGovernor(Brain):
    name = "risk-governor"
    weight = 0.0

    def veto(self, decision, context: dict) -> str | None:
        cfg = self.config.get("risk", {})
        account = context.get("account") or {}
        positions = context.get("positions") or []
        clock = context.get("clock") or {}
        proposal = decision.proposal

        if not context.get("spot") and not clock.get("is_open", False):
            return "Market is closed"

        if account.get("equity", 0) <= 0:
            return "Account equity unavailable"

        max_positions = cfg.get("max_open_positions", 4)
        if len(positions) >= max_positions:
            return f"Max open positions reached ({len(positions)}/{max_positions})"

        if proposal is not None:
            same_underlying = [
                p for p in positions if p.get("underlying") == proposal.underlying
            ]
            if same_underlying:
                return f"Already exposed to {proposal.underlying}"

        day_pnl = self._day_realized_pnl(context)
        daily_cap = float(cfg.get("daily_loss_cap_pct", 0.02)) * account.get("equity", 0)
        if daily_cap > 0 and day_pnl < -daily_cap:
            return f"Daily loss cap hit ({day_pnl:.2f} < -{daily_cap:.2f})"

        if proposal is not None and proposal.asset_class == "option":
            risk_budget = float(cfg.get("max_risk_per_trade_pct", 0.01)) * account.get("equity", 0)
            cost = (proposal.max_debit or 0) * 100 * proposal.qty
            if cost > risk_budget and proposal.qty > 1:
                reduced = max(1, int(risk_budget // (cost / proposal.qty)))
                logging.info(f"[{self.name}] reducing qty {proposal.qty} -> {reduced} for budget")
                proposal.qty = reduced
                cost = (proposal.max_debit or 0) * 100 * proposal.qty
            if cost > risk_budget * 1.5:
                return (
                    f"Trade cost ${cost:.2f} exceeds risk budget "
                    f"${risk_budget:.2f}"
                )

        if proposal is not None and proposal.asset_class == "crypto":
            equity = account.get("equity", 0)
            crypto_cap = float(
                (self.config.get("crypto") or {}).get("max_total_exposure_pct", 0.10)
            ) * equity
            current_crypto = sum(
                p.get("market_value", p.get("current_price", 0) * p.get("qty", 0))
                for p in positions
                if p.get("asset_class") == "crypto"
            )
            if current_crypto + (proposal.max_debit or 0) > crypto_cap:
                return (
                    f"Crypto exposure cap hit (${current_crypto:.0f} held "
                    f"+ ${proposal.max_debit or 0:.0f} new > ${crypto_cap:.0f})"
                )

        return None

    @staticmethod
    def _day_realized_pnl(context: dict) -> float:
        history = context.get("journal_today") or []
        today = datetime.now(timezone.utc).date()
        pnl = 0.0
        for row in history:
            try:
                if datetime.fromisoformat(str(row.get("timestamp", ""))).date() == today:
                    pnl += float(row.get("realized_pnl", 0) or 0)
            except ValueError:
                continue
        return pnl
