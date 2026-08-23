import logging

from agent.brains.base import Brain
from agent.models import Vote
from signals.macd_v4 import format_technical_summary

SYSTEM_PROMPT = """You are the Technical Analyst brain inside an autonomous options-trading council.
You receive a technical snapshot computed from closed 15-minute bars (MACD state, RSI with divergence flags,
fractal market structure, and higher-timeframe EMA regimes).

Your job: judge whether evidence supports a directional bias for a SHORT-DATED OPTIONS position over the
next few days. Options decay fast, so require confluence rather than acting on one indicator.

Respond ONLY with JSON:
{"direction": "bullish" | "bearish" | "neutral",
 "confidence": 0.0-1.0,
 "reasoning": "2-4 sentences citing specific signals"}

Rules of thumb:
- MACD cross aligned with hourly/daily regime and structure trend is strong.
- RSI divergence AGAINST the crossover is a warning; reduce confidence or flip to neutral.
- If evidence conflicts, say neutral with low confidence."""


def _fallback_vote(context) -> Vote:
    ctx = context.get("technicals", {})
    score = 0
    if ctx.get("macd_crossover") == "bullish":
        score += 2
    elif ctx.get("macd_crossover") == "bearish":
        score -= 2
    if ctx.get("htf_hourly_trend") == "bullish":
        score += 1
    elif ctx.get("htf_hourly_trend") == "bearish":
        score -= 1
    if ctx.get("htf_daily_trend") == "bullish":
        score += 1
    elif ctx.get("htf_daily_trend") == "bearish":
        score -= 1
    if ctx.get("rsi_bullish_divergence"):
        score += 1
    if ctx.get("rsi_bearish_divergence"):
        score -= 1

    if score >= 3:
        return Vote("technical-analyst", "bullish", 0.55, "Deterministic fallback: MACD + regime alignment")
    if score <= -3:
        return Vote("technical-analyst", "bearish", 0.55, "Deterministic fallback: MACD + regime alignment")
    return Vote("technical-analyst", "neutral", 0.2, "Deterministic fallback: mixed signals")


class TechnicalAnalyst(Brain):
    name = "technical-analyst"
    weight = 1.5

    def decide(self, symbol: str, context: dict) -> Vote:
        summary = format_technical_summary(context.get("technicals", {}))
        prompt = (
            f"{summary}\n\n"
            f"Recent closes (last 10 closed bars): "
            f"{[round(float(x), 2) for x in context['bars']['close'].tail(10).tolist()]}\n\n"
            "Give your directional assessment as JSON."
        )

        parsed = None
        if self.llm and self.llm.enabled:
            parsed = self.llm.complete_json(SYSTEM_PROMPT, prompt)

        if not parsed or str(parsed.get("direction", "")).lower() not in ("bullish", "bearish", "neutral"):
            logging.info(f"[{self.name}] LLM unavailable/invalid -> deterministic fallback")
            return _fallback_vote(context)

        direction = str(parsed["direction"]).lower()
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        return self._vote(direction, confidence, str(parsed.get("reasoning", ""))[:500])
