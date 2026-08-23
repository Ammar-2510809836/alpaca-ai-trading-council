import csv
import json
import logging
import os
from datetime import datetime, timezone


class Journal:
    def __init__(self, directory: str = "journals"):
        os.makedirs(directory, exist_ok=True)
        self.decisions_path = os.path.join(directory, "decisions.csv")
        self.trades_path = os.path.join(directory, "trades.csv")
        self._ensure(self.decisions_path, self._decision_header())
        self._ensure(self.trades_path, self._trade_header())

    @staticmethod
    def _decision_header():
        return [
            "timestamp",
            "symbol",
            "action",
            "confidence",
            "summary",
            "vetoed_by",
            "veto_reason",
            "votes",
        ]

    @staticmethod
    def _trade_header():
        return [
            "timestamp",
            "underlying",
            "symbol",
            "asset_class",
            "structure",
            "direction",
            "qty",
            "limit_price",
            "client_order_id",
            "status",
        ]

    def _ensure(self, path, header):
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerow(header)
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                first = handle.readline()
            if header[0] not in first:
                body = ""
                with open(path, "r", encoding="utf-8") as handle:
                    body = handle.read()
                with open(path, "w", newline="", encoding="utf-8") as handle:
                    csv.writer(handle).writerow(header)
                    handle.write(body if body.endswith("\n") or not body else body + "\n")
        except OSError:
            pass

    def log_decision(self, decision, context=None):
        try:
            self._ensure(self.decisions_path, self._decision_header())
        except Exception:
            pass
        row = [
            datetime.now(timezone.utc).isoformat(),
            decision.symbol,
            decision.action,
            round(decision.confidence, 4),
            decision.summary,
            decision.vetoed_by or "",
            decision.veto_reason or "",
            json.dumps(
                [
                    {
                        "brain": v.brain,
                        "direction": v.direction,
                        "confidence": round(v.confidence, 3),
                        "reasoning": v.reasoning,
                    }
                    for v in decision.votes
                ]
            ),
        ]
        try:
            with open(self.decisions_path, "a", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerow(row)
        except Exception as exc:
            logging.error(f"Journal decision write failed: {exc}")

    def log_trade(
        self,
        underlying,
        symbol,
        asset_class,
        structure,
        direction,
        qty,
        limit_price,
        client_order_id,
        status,
    ):
        try:
            self._ensure(self.trades_path, self._trade_header())
        except Exception:
            pass
        row = [
            datetime.now(timezone.utc).isoformat(),
            underlying,
            symbol,
            asset_class,
            structure,
            direction,
            qty,
            limit_price,
            client_order_id,
            status,
        ]
        try:
            with open(self.trades_path, "a", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerow(row)
        except Exception as exc:
            logging.error(f"Journal trade write failed: {exc}")
