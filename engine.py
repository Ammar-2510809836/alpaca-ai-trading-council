import json
import logging
import os
import time
from datetime import datetime, timezone

from agent.brains import Council, NewsBrain, OptionsStrategist, RiskGovernor, TechnicalAnalyst
from agent.models import TradeProposal
from journal import Journal
from notify import send_message, trade_alert
from signals.macd_v4 import build_technical_context


class TradingEngine:
    def __init__(self, broker, mcp_bridge, llm, config: dict, dry_run: bool = False):
        self.broker = broker
        self.mcp = mcp_bridge
        self.llm = llm
        self.config = config
        self.dry_run = dry_run

        tools = None
        if broker is not None:
            from agent.tools import AgentTools

            tools = AgentTools(broker, mcp_bridge)

        self.council = Council(
            analyst=TechnicalAnalyst(broker=broker, llm=llm, tools=tools, config=config),
            news_brain=NewsBrain(broker=broker, llm=llm, tools=tools, config=config),
            strategist=OptionsStrategist(broker=broker, llm=llm, tools=tools, config=config),
            risk_governor=RiskGovernor(broker=broker, llm=None, tools=tools, config=config),
            config=config,
        )
        self.journal = Journal(config.get("journal_dir", "journals"))
        self.tracking_path = os.path.join(self.config.get("journal_dir", "journals"), "position_tracking.json")

    def _write_state(self, phase: str, message: str = "", symbol: str = ""):
        try:
            os.makedirs(self.config.get("journal_dir", "journals"), exist_ok=True)
            state = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "phase": phase,
                "symbol": symbol,
                "message": message,
                "llm_model": getattr(self.llm, "model", ""),
                "dry_run": self.dry_run,
            }
            path = os.path.join(self.config.get("journal_dir", "journals"), "engine_state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
        except OSError:
            pass

    def _load_tracking(self) -> dict:
        if os.path.exists(self.tracking_path):
            try:
                with open(self.tracking_path, "r", encoding="utf-8") as h:
                    return json.load(h)
            except Exception:
                return {}
        return {}

    def _save_tracking(self, data: dict):
        try:
            os.makedirs(os.path.dirname(self.tracking_path), exist_ok=True)
            with open(self.tracking_path, "w", encoding="utf-8") as h:
                json.dump(data, h, indent=2)
        except Exception as exc:
            logging.warning(f"Failed to save position tracking: {exc}")

    def run_forever(self):
        interval = int(self.config.get("cycle_seconds", 300))
        logging.info(f"Engine started (cycle={interval}s, dry_run={self.dry_run})")
        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logging.exception(f"Cycle failed: {exc}")
            time.sleep(interval)

    def run_cycle(self):
        clock = self.broker.get_clock() if self.broker else {"is_open": True}
        account = self.broker.get_account() if self.broker else {
            "equity": 100000,
            "cash": 100000,
            "buying_power": 100000,
            "portfolio_value": 100000,
        }
        positions = self.broker.get_positions() if self.broker else []

        logging.info(
            f"Cycle start | market_open={clock.get('is_open')} "
            f"equity={account.get('equity')} open_positions={len(positions)}"
        )

        equities_open = bool(clock.get("is_open")) or bool(self.config.get("ignore_market_hours"))
        stocks, cryptos = self.current_watchlists()
        logging.info(
            f"Watchlist this cycle: stocks={stocks} crypto={cryptos} "
            f"(equities {'OPEN' if equities_open else 'closed'}, crypto 24/7)"
        )

        effective_clock = dict(clock)
        if self.config.get("ignore_market_hours") and not clock.get("is_open"):
            logging.warning("IGNORE_MARKET_HOURS active - orders will queue until next open")
            effective_clock["is_open"] = True

        if not equities_open and not cryptos:
            logging.info("All markets closed; skipping entries")
            self._write_state(
                "idle",
                f"Markets closed - next equity open {clock.get('next_open', 'unknown')}; crypto resumes next cycle",
            )
            return

        self._write_state("cycle_start", f"Cycle starting | {len(stocks)} stocks + {len(cryptos)} crypto")

        # 1. Manage Dynamic Exits and Trailing Stops on Active Positions
        self._write_state("exits", f"Evaluating dynamic exits & trailing stops on {len(positions)} position(s)")
        self.manage_exits(positions)

        # 2. Evaluate Potential New Entries
        if equities_open:
            for symbol in stocks:
                try:
                    self._evaluate_symbol(symbol, effective_clock, account, positions, asset_class="stock")
                except Exception as exc:
                    logging.exception(f"Error evaluating {symbol}: {exc}")

        for symbol in cryptos:
            try:
                self._evaluate_symbol(symbol, effective_clock, account, positions, asset_class="crypto")
            except Exception as exc:
                logging.exception(f"Error evaluating {symbol}: {exc}")

        self._write_state(
            "idle",
            f"Sleeping {int(self.config.get('cycle_seconds', 300))}s until next cycle",
        )

    def current_symbols(self):
        stocks, cryptos = self.current_watchlists()
        return stocks + cryptos

    def current_watchlists(self):
        path = self.config.get("symbols_file", "symbols.txt")
        stocks, cryptos = [], []
        in_crypto_section = False
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.split("#")[0].strip()
                    if not line:
                        continue
                    lowered = line.lower()
                    if lowered.startswith("[crypto]"):
                        in_crypto_section = True
                        continue
                    if lowered.startswith("["):
                        in_crypto_section = False
                        continue
                    token = line.upper()
                    target = cryptos if in_crypto_section else stocks
                    if token not in target:
                        target.append(token)
        except OSError:
            pass

        if not stocks and not cryptos:
            stocks = list(self.config.get("symbols", []))
        return stocks, cryptos

    def _evaluate_symbol(self, symbol, clock, account, positions, asset_class="stock"):
        clean_sym = symbol.replace("/", "").upper()
        pending = self.broker.get_open_orders() if self.broker else []
        if any(clean_sym == str(s).replace("/", "").upper() or str(s).replace("/", "").upper().startswith(clean_sym) for s in pending):
            logging.info(f"{symbol}: order already working, skipping")
            return

        existing = [
            p for p in positions
            if str(p.get("underlying", "")).replace("/", "").upper() == clean_sym
            or str(p.get("symbol", "")).replace("/", "").upper() == clean_sym
        ]
        if existing:
            logging.info(f"{symbol}: already holding {len(existing)} position(s), skipping duplicate entry")
            return

        timeframe = self.config.get("timeframe", "15Min")
        lookback = int(self.config.get("lookback_days", 10))

        self._write_state(
            "market_data",
            f"Fetching {timeframe} bars from Alpaca ({asset_class})",
            symbol,
        )

        if self.broker is None:
            bars = _synthetic_bars()
        elif asset_class == "crypto":
            bars = self.broker.get_crypto_bars(symbol, timeframe=timeframe, days=lookback)
        else:
            bars = self.broker.get_stock_bars(symbol, timeframe=timeframe, days=lookback)

        if bars is None or len(bars) < 120:
            logging.warning(f"{symbol}: insufficient bars ({0 if bars is None else len(bars)}), skipping")
            return

        context = {
            "clock": clock,
            "symbol": symbol,
            "bars": bars,
            "technicals": build_technical_context(bars, symbol),
            "news": [],
            "option_chain": None,
            "account": account,
            "positions": positions,
            "journal_today": [],
            "spot": asset_class == "crypto",
        }
        context["price"] = context["technicals"]["price"]

        self._write_state(
            "indicators",
            f"Computing MACD / RSI divergence / fractal structure on {len(bars)} closed bars",
            symbol,
        )

        llm_label = getattr(self.llm, "model", "deterministic-fallback")
        self._write_state("llm_council", f"LLM brains voting ({llm_label})", symbol)

        decision = self.council.run(symbol, context)
        self.journal.log_decision(decision, context)

        self._write_state(
            "decision",
            f"{decision.action}: {decision.summary}",
            symbol,
        )

        votes_text = " | ".join(f"{v.brain}:{v.direction}({v.confidence:.2f})" for v in decision.votes)
        logging.info(f"[{symbol}] {decision.action} | {decision.summary} | {votes_text}")

        webhook = self.config.get("discord_webhook")
        if decision.action != "hold" or decision.veto_reason:
            send_message(
                f"**[{symbol}] Council decision: `{decision.action}`**\n"
                f"{decision.summary}\n{votes_text}",
                webhook,
            )

        if decision.action in ("buy_option_structure", "buy_spot_crypto") and decision.proposal:
            self._write_state(
                "execution",
                f"Placing {decision.proposal.structure} on {symbol}",
                symbol,
            )
            self.execute_proposal(decision.proposal)

    def execute_proposal(self, proposal: TradeProposal):
        if proposal.asset_class == "crypto":
            self._execute_spot_crypto(proposal)
            return

        label = proposal.structure.replace("_", "-")
        qty = max(1, int(proposal.qty))
        direction = "bullish" if "bull" in proposal.structure or "call" in proposal.structure else "bearish"

        if self.dry_run:
            logging.info(f"[DRY-RUN] Would place {proposal.structure} on {proposal.underlying}: {proposal.legs} x{qty}")
            self.journal.log_trade(
                proposal.underlying,
                ",".join(l["occ_symbol"] for l in proposal.legs),
                proposal.asset_class,
                proposal.structure,
                direction,
                qty,
                proposal.limit_price,
                "dry-run",
                "skipped",
            )
            return

        result = None
        if len(proposal.legs) > 1:
            legs = [
                {
                    "action": leg["action"],
                    "occ_symbol": leg["occ_symbol"],
                    "ratio": int(leg.get("ratio", 1)),
                }
                for leg in proposal.legs
            ]
            result = self.broker.submit_option_spread(legs, qty, proposal.limit_price or 0, label)
        else:
            leg = proposal.legs[0]
            side = "buy"
            limit = round(float(leg.get("mid") or proposal.limit_price or 0), 2)
            result = self.broker.submit_option_limit_order(
                leg["occ_symbol"], side, qty, limit, label
            )

        status = "submitted" if result else "failed"
        client_id = (result or {}).get("client_order_id", "n/a")
        symbols_joined = ",".join(l["occ_symbol"] for l in proposal.legs)
        self.journal.log_trade(
            proposal.underlying,
            symbols_joined,
            proposal.asset_class,
            proposal.structure,
            direction,
            qty,
            proposal.limit_price,
            client_id,
            status,
        )
        trade_alert(
            self.config.get("discord_webhook"),
            symbols_joined,
            proposal.underlying,
            proposal.structure,
            direction,
            qty,
            proposal.limit_price,
            client_id,
            "paper",
        )

    def _execute_spot_crypto(self, proposal: TradeProposal):
        qty = float(proposal.qty)
        if self.dry_run:
            logging.info(f"[DRY-RUN] Would buy {qty} {proposal.underlying} (spot crypto)")
            self.journal.log_trade(
                proposal.underlying, proposal.underlying, "crypto", "long_spot",
                "bullish", qty, None, "dry-run", "skipped",
            )
            return

        result = self.broker.submit_crypto_order(
            proposal.underlying, "buy", qty, "long-spot"
        )
        status = "submitted" if result else "failed"
        client_id = (result or {}).get("client_order_id", "n/a")
        self.journal.log_trade(
            proposal.underlying, proposal.underlying, "crypto", "long_spot",
            "bullish", qty, proposal.max_debit, client_id, status,
        )
        trade_alert(
            self.config.get("discord_webhook"),
            proposal.underlying,
            proposal.underlying,
            "long_spot",
            "bullish",
            round(qty, 6),
            proposal.max_debit,
            client_id,
            "paper",
        )

    def manage_exits(self, positions=None):
        """Dynamic exit manager with Breakeven protection, Trailing stop profit locks,

        AI Council position re-evaluation, and DTE force closes.
        """
        exits_cfg = self.config.get("exits", {})
        if self.broker is None:
            return
        if positions is None:
            positions = self.broker.get_positions()

        tracker = self._load_tracking()
        active_syms = set()

        for position in positions:
            asset_kind = position.get("asset_class")
            if asset_kind not in ("option", "crypto"):
                continue

            symbol = position["symbol"]
            active_syms.add(symbol)
            entry = float(position.get("avg_entry_price") or 0)
            current = float(position.get("current_price") or entry)
            side = position.get("side", "long")

            if entry <= 0 or current <= 0:
                continue

            # 1. Update High-Water Mark & Live Trend Tracking
            eval_res = self._evaluate_position_trend(symbol, asset_kind)
            reversal = eval_res.get("reversal")

            if symbol not in tracker:
                tracker[symbol] = {
                    "symbol": symbol,
                    "underlying": position.get("underlying", symbol),
                    "asset_class": asset_kind,
                    "entry_price": entry,
                    "peak_price": current,
                    "peak_gain_pct": max(0.0, (current / entry - 1)),
                    "breakeven_active": False,
                    "entry_time": datetime.now(timezone.utc).isoformat(),
                    "last_checked": datetime.now(timezone.utc).isoformat(),
                    "trend_status": eval_res.get("trend_status", "🟢 Active"),
                    "trend_details": eval_res.get("trend_details", "Live"),
                    "action_plan": "⏳ Dynamic Monitoring",
                }
            else:
                track = tracker[symbol]
                track["entry_price"] = entry
                track["last_checked"] = datetime.now(timezone.utc).isoformat()
                track["trend_status"] = eval_res.get("trend_status", "🟢 Active")
                track["trend_details"] = eval_res.get("trend_details", "Live")
                if current > track.get("peak_price", entry):
                    track["peak_price"] = current
                    track["peak_gain_pct"] = max(0.0, (current / entry - 1))

            track = tracker[symbol]
            gain = (current / entry - 1) if side == "long" else (1 - current / entry)
            peak_gain = track.get("peak_gain_pct", 0.0)
            reason = None

            # --- A. CRYPTO POSITION DYNAMIC EXITS ---
            if asset_kind == "crypto":
                be_thresh = float(exits_cfg.get("crypto_breakeven_gain_pct", 0.03))
                trail_act = float(exits_cfg.get("crypto_trailing_activation_pct", 0.04))
                trail_pb = float(exits_cfg.get("crypto_trailing_pullback_pct", 0.02))
                hard_stop = float(exits_cfg.get("crypto_hard_stop_pct", 0.06))
                hard_target = float(exits_cfg.get("crypto_hard_target_pct", 0.12))

                # 1. Breakeven Activation
                if gain >= be_thresh and not track.get("breakeven_active"):
                    track["breakeven_active"] = True
                    logging.info(f"[{symbol}] Breakeven stop ACTIVATED (+{gain:.2%})")

                # Action Plan Diagnosis
                if track.get("breakeven_active"):
                    track["action_plan"] = f"🛡️ Breakeven Protected (+{gain:.2%})"
                elif peak_gain >= trail_act:
                    track["action_plan"] = f"📈 Trailing Active (Peak: +{peak_gain:.1%})"
                else:
                    needed = max(0.0, (be_thresh - gain)) * 100
                    track["action_plan"] = f"⏳ Breakeven at +3.0% (needs +{needed:.2f}%)"

                # 2. Breakeven Stop Trigger (Lock capital once in profit)
                if track.get("breakeven_active") and gain <= 0.002:
                    reason = f"🛡️ Breakeven stop hit (secured profit, peak was +{peak_gain:.1%})"

                # 3. Dynamic Trailing Stop (Protect peak profits)
                elif peak_gain >= trail_act:
                    pullback = (track["peak_price"] - current) / track["peak_price"]
                    if pullback >= trail_pb:
                        reason = f"📈 Trailing stop triggered (locked in +{gain:.1%}, pulled back {pullback:.1%} from peak)"

                # 4. Active AI Council Re-Evaluation Exit
                elif exits_cfg.get("council_reversal_exit", True) and reversal:
                    reason = f"🧠 AI Council reversal: {reversal} (early profit lock at {gain:+.1%})"

                # 5. Hard Target / Hard Stop Fallbacks
                elif gain >= hard_target:
                    reason = f"🎯 Profit target hit (+{gain:.1%})"
                elif gain <= -hard_stop:
                    reason = f"🛑 Hard stop-loss hit ({gain:.1%})"

            # --- B. OPTIONS POSITION DYNAMIC EXITS ---
            elif asset_kind == "option":
                dte = self._dte(symbol)
                force_close_dte = int(exits_cfg.get("force_close_dte", 1))
                opt_be_thresh = float(exits_cfg.get("options_breakeven_gain_pct", 0.20))
                opt_trail_act = float(exits_cfg.get("options_trailing_activation_pct", 0.30))
                opt_trail_pb = float(exits_cfg.get("options_trailing_pullback_pct", 0.15))
                opt_stop = float(exits_cfg.get("stop_loss_pct", 0.35))
                opt_target = float(exits_cfg.get("take_profit_pct", 0.60))

                # 1. DTE Force Close (Avoid pin risk/assignment)
                if dte is not None and dte <= force_close_dte:
                    reason = f"⏳ DTE {dte} <= {force_close_dte} (expiration safety exit)"

                # 2. Breakeven Activation & Trigger
                elif gain >= opt_be_thresh and not track.get("breakeven_active"):
                    track["breakeven_active"] = True
                    logging.info(f"[{symbol}] Options Breakeven stop ACTIVATED (+{gain:.1%})")

                # Action plan
                if track.get("breakeven_active"):
                    track["action_plan"] = f"🛡️ Breakeven Protected (Peak: +{peak_gain:.1%})"
                else:
                    track["action_plan"] = f"⏳ Target +60% | Breakeven at +20%"

                if not reason and track.get("breakeven_active") and gain <= 0.02:
                    reason = f"🛡️ Options Breakeven stop hit (secured capital, peak was +{peak_gain:.1%})"

                # 3. Dynamic Trailing Stop on Options
                elif not reason and peak_gain >= opt_trail_act:
                    pullback = (track["peak_price"] - current) / track["peak_price"]
                    if pullback >= opt_trail_pb:
                        reason = f"📈 Options Trailing stop (locked in +{gain:.1%}, peak was +{peak_gain:.1%})"

                # 4. Fallback Target & Stop
                elif not reason and gain >= opt_target:
                    reason = f"🎯 Options target hit (+{gain:.1%})"
                elif not reason and gain <= -opt_stop:
                    reason = f"🛑 Options stop-loss hit ({gain:.1%})"

            # Execute Exit if Triggered
            if reason:
                logging.info(f"Closing position {symbol}: {reason}")
                ok = False if self.dry_run else self.broker.close_position(symbol)
                send_message(
                    f"**Exit** `{symbol}` - {reason}" + (" *(dry-run)*" if self.dry_run else ""),
                    self.config.get("discord_webhook"),
                )
                self.journal.log_trade(
                    position.get("underlying", symbol),
                    symbol,
                    asset_kind,
                    "exit",
                    "close",
                    float(position.get("qty", 1)),
                    current,
                    "",
                    "closed-dryrun" if (self.dry_run and ok is False) else "closed",
                )
                if symbol in tracker:
                    del tracker[symbol]

        # Clean up tracker for closed positions
        for sym in list(tracker.keys()):
            if sym not in active_syms:
                del tracker[sym]

        self._save_tracking(tracker)

    def _evaluate_position_trend(self, symbol: str, asset_class: str) -> dict:
        """Evaluates live indicator regime (MACD, RSI, EMA50) and returns trend diagnosis."""
        try:
            timeframe = self.config.get("timeframe", "15Min")
            bars = None
            if self.broker:
                if asset_class == "crypto":
                    bars = self.broker.get_crypto_bars(symbol, timeframe=timeframe, days=5)
                else:
                    bars = self.broker.get_stock_bars(symbol, timeframe=timeframe, days=5)

            if bars is None or len(bars) < 60:
                return {
                    "trend_status": "🟢 Active (Healthy)",
                    "trend_details": "Price above support",
                    "reversal": None,
                }

            technicals = build_technical_context(bars, symbol)
            hist = float(technicals.get("macd_hist", 0) or 0)
            hist_slope = str(technicals.get("macd_hist_slope", "flat"))
            rsi_val = float(technicals.get("rsi", 50) or 50)
            rsi_div = str(technicals.get("rsi_divergence") or "none")
            ema_regime = str(technicals.get("ema50_regime", "neutral"))

            # Check for strong bearish reversal confluence
            bearish_signals = []
            if rsi_div == "bearish":
                bearish_signals.append("Bearish RSI divergence")
            if hist < 0 and hist_slope == "falling":
                bearish_signals.append("MACD histogram falling")
            if ema_regime == "bearish":
                bearish_signals.append("Price below EMA50")

            reversal = " + ".join(bearish_signals) if len(bearish_signals) >= 2 else None

            # Determine Trend Status
            if ema_regime == "bullish" and hist >= 0 and rsi_val >= 50:
                trend = "🟢 Strong Bullish Trend"
            elif ema_regime == "bullish":
                trend = "🟢 Bullish Regime"
            elif ema_regime == "bearish" and hist <= 0:
                trend = "🔴 Bearish Weakening"
            else:
                trend = "🟡 Consolidating / Ranging"

            details = f"EMA50: {ema_regime} · RSI: {rsi_val:.1f} · MACD: {hist_slope}"
            return {
                "trend_status": trend,
                "trend_details": details,
                "reversal": reversal,
            }
        except Exception as exc:
            logging.warning(f"Trend evaluation error for {symbol}: {exc}")
            return {
                "trend_status": "🟢 Active Monitoring",
                "trend_details": "Live checks active",
                "reversal": None,
            }

    @staticmethod
    def _dte(occ_symbol: str):
        from broker.alpaca_client import parse_occ_symbol

        parsed = parse_occ_symbol(occ_symbol)
        if not parsed:
            return None
        expiry = datetime.strptime(parsed["expiry"], "%Y-%m-%d").date()
        return (expiry - datetime.now(timezone.utc).date()).days


def _synthetic_bars():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(7)
    n = 400
    steps = rng.normal(0.0005, 0.008, n)
    close = 180 * np.exp(np.cumsum(steps))
    high = close * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.002, n)))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    times = pd.date_range(end=datetime.now(timezone.utc), periods=n, freq="15min")

    return pd.DataFrame(
        {
            "time": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1e5, 5e5, n),
        }
    )
