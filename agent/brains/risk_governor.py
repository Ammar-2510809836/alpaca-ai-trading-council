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
        equity = float(account.get("equity", 0) or 0)
        cash = float(account.get("cash", 0) or 0)

        # 1. Market Hours Check (Options/Stocks require market open; crypto is 24/7)
        if not context.get("spot") and not clock.get("is_open", False):
            return "Market is closed"

        if equity <= 0:
            return "Account equity unavailable"

        # 2. Max Open Positions Limit
        max_positions = int(cfg.get("max_open_positions", 4))
        if len(positions) >= max_positions:
            return f"Max open positions reached ({len(positions)}/{max_positions})"

        # 3. Duplicate Underlying Check
        if proposal is not None:
            clean_underlying = str(proposal.underlying or "").replace("/", "").upper()
            same_underlying = [
                p for p in positions
                if str(p.get("underlying", "")).replace("/", "").upper() == clean_underlying
                or str(p.get("symbol", "")).replace("/", "").upper() == clean_underlying
            ]
            if same_underlying:
                return f"Already exposed to {proposal.underlying}"

        # 4. Daily Portfolio Loss Cap
        day_pnl = self._day_realized_pnl(context)
        daily_cap = float(cfg.get("daily_loss_cap_pct", 0.03)) * equity
        if daily_cap > 0 and day_pnl < -daily_cap:
            return f"Daily loss cap hit ({day_pnl:.2f} < -{daily_cap:.2f})"

        # 5. Options Sizing & Risk Budget
        if proposal is not None and proposal.asset_class == "option":
            risk_budget = float(cfg.get("max_risk_per_trade_pct", 0.01)) * equity
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

            # Single asset exposure cap on stock/option
            single_cap = float(cfg.get("max_single_asset_exposure_pct", 0.10)) * equity
            if cost > single_cap:
                return f"Single asset exposure cap hit (${cost:.0f} > ${single_cap:.0f})"

        # 6. Crypto Exposure & Concentration Caps
        if proposal is not None and proposal.asset_class == "crypto":
            trade_cost = float(proposal.max_debit or 0)
            if trade_cost > cash:
                return f"Insufficient cash (${cash:,.2f} available < ${trade_cost:,.2f} required)"

            # Single crypto asset cap (max 10% per coin)
            single_asset_cap = float(cfg.get("max_single_asset_exposure_pct", 0.10)) * equity
            clean_sym = str(proposal.underlying or "").replace("/", "").upper()
            current_asset_val = sum(
                float(p.get("market_value", float(p.get("current_price", 0)) * float(p.get("qty", 0))))
                for p in positions
                if str(p.get("symbol", "")).replace("/", "").upper() == clean_sym
                or str(p.get("underlying", "")).replace("/", "").upper() == clean_sym
            )
            if current_asset_val + trade_cost > single_asset_cap:
                return (
                    f"Single asset concentration cap hit (${current_asset_val:,.0f} held "
                    f"+ ${trade_cost:,.0f} new > ${single_asset_cap:,.0f} [10% limit])"
                )

            # Total crypto exposure cap (max 20% across all crypto)
            crypto_cap = float(
                (self.config.get("crypto") or {}).get("max_total_exposure_pct", 0.20)
            ) * equity
            current_crypto = sum(
                float(p.get("market_value", float(p.get("current_price", 0)) * float(p.get("qty", 0))))
                for p in positions
                if p.get("asset_class") == "crypto"
            )
            if current_crypto + trade_cost > crypto_cap:
                return (
                    f"Total crypto portfolio cap hit (${current_crypto:,.0f} held "
                    f"+ ${trade_cost:,.0f} new > ${crypto_cap:,.0f} [20% limit])"
                )

            # Cash reserve buffer
            min_cash_pct = float(cfg.get("min_cash_reserve_pct", 0.20))
            if (cash - trade_cost) < (equity * min_cash_pct):
                return f"Cash reserve buffer protected (requires maintaining {min_cash_pct:.0%} cash reserves)"

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
