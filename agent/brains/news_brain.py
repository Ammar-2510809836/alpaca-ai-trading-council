import logging
import time

from agent.brains.base import Brain
from agent.models import Vote
from signals.macd_v4 import format_news_summary

VOTE_CACHE_TTL = 1800

SYSTEM_PROMPT = """You are the News & Sentiment brain inside an autonomous options-trading council.
You receive recent headlines for one stock. Judge whether the news flow supports a bullish or bearish
bias for the next few trading days, and whether any event (earnings, FDA, litigation, guidance) makes
short-dated options dangerous.

Respond ONLY with JSON:
{"direction": "bullish" | "bearish" | "neutral",
 "confidence": 0.0-1.0,
 "reasoning": "2-3 sentences"}

If headlines are stale or irrelevant, return neutral with low confidence."""


class NewsBrain(Brain):
    name = "news-sentiment"
    weight = 1.0

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._vote_cache = {}

    def decide(self, symbol: str, context: dict) -> Vote:
        cached = self._vote_cache.get(symbol)
        if cached and time.time() - cached[0] < VOTE_CACHE_TTL:
            return cached[1]

        news_items = context.get("news") or []

        if not news_items and self.tools is not None:
            news_items = self.tools.news(symbol)
            context["news"] = news_items

        parsed = None
        if self.llm and self.llm.enabled and news_items:
            prompt = (
                f"Symbol: {symbol}\n\nHeadlines:\n{format_news_summary(news_items)}\n\n"
                "Assess sentiment as JSON."
            )
            parsed = self.llm.complete_json(SYSTEM_PROMPT, prompt)

        if not parsed or str(parsed.get("direction", "")).lower() not in ("bullish", "bearish", "neutral"):
            if not news_items:
                return self._vote("neutral", 0.0, "No news available; abstaining")
            logging.info(f"[{self.name}] LLM unavailable -> neutral vote")
            return self._vote("neutral", 0.1, "LLM unavailable for sentiment analysis")

        direction = str(parsed["direction"]).lower()
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        vote = self._vote(direction, confidence * 0.9, str(parsed.get("reasoning", ""))[:500])
        self._vote_cache[symbol] = (time.time(), vote)
        return vote
