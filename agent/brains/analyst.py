import logging

from agent.brains.base import Brain
from agent.models import Vote
from signals.macd_v4 import format_technical_summary

SYSTEM_PROMPT = """You are the Technical Analyst brain inside an autonomous algorithmic trading council.
You receive a technical snapshot computed from closed 15-minute bars.

CORE STRATEGY: EMA 9 & EMA 21 Crossover Strategy.
- PRIMARY BUY TRIGGER: 9 EMA crosses ABOVE 21 EMA (or 9 EMA > 21 EMA with strong expanding positive spread) -> BULLISH.
- PRIMARY SELL / EXIT TRIGGER: 9 EMA crosses BELOW 21 EMA (or 9 EMA < 21 EMA with negative momentum) -> BEARISH.
- CONFLUENCE CONFIRMATION: Use MACD crossover, RSI divergence, and Hourly EMA50 to confirm momentum.

Respond ONLY with JSON:
{"direction": "bullish" | "bearish" | "neutral",
 "confidence": 0.0-1.0,
 "reasoning": "2-4 sentences explicitly stating EMA 9 vs EMA 21 relationship and confirming signals"}

Rules of thumb:
- Bullish EMA 9/21 cross aligned with MACD or price above EMA50 is high confidence (0.65 - 0.85).
- Bearish EMA 9/21 cross indicates immediate trend exhaustion or downside reversal.
- If EMA 9/21 is neutral or conflicting with other indicators, reduce confidence."""


def _fallback_vote(context) -> Vote:
    ctx = context.get("technicals", {})
    score = 0

    # 1. Primary: EMA 9 & 21 Crossover
    if ctx.get("ema_9_21_crossover") == "bullish":
        score += 3
    elif ctx.get("ema_9_21_crossover") == "bearish":
        score -= 3

    if ctx.get("ema_9_21_regime") == "bullish":
        score += 1
    elif ctx.get("ema_9_21_regime") == "bearish":
        score -= 1

    # 2. Confluence: MACD, RSI, HTF
    if ctx.get("macd_crossover") == "bullish":
        score += 1
    elif ctx.get("macd_crossover") == "bearish":
        score -= 1
    if ctx.get("htf_hourly_trend") == "bullish":
        score += 1
    elif ctx.get("htf_hourly_trend") == "bearish":
        score -= 1
    if ctx.get("rsi_bullish_divergence"):
        score += 1
    if ctx.get("rsi_bearish_divergence"):
        score -= 1

    if score >= 3:
        return Vote("technical-analyst", "bullish", 0.70, "Deterministic fallback: EMA 9/21 Bullish Cross + Momentum")
    if score <= -3:
        return Vote("technical-analyst", "bearish", 0.70, "Deterministic fallback: EMA 9/21 Bearish Cross + Momentum")
    return Vote("technical-analyst", "neutral", 0.2, "Deterministic fallback: EMA 9/21 neutral / mixed signals")


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
