from agent.models import Vote


class Brain:
    name = "base"
    weight = 1.0

    def __init__(self, broker=None, llm=None, tools=None, config=None):
        self.broker = broker
        self.llm = llm
        self.tools = tools
        self.config = config or {}

    def decide(self, symbol: str, context: dict) -> Vote:
        raise NotImplementedError

    def _vote(self, direction: str, confidence: float, reasoning: str) -> Vote:
        confidence = max(0.0, min(1.0, float(confidence)))
        return Vote(brain=self.name, direction=direction, confidence=confidence, reasoning=reasoning)
