from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OptionLegPlan:
    action: str
    symbol: str
    ratio: int = 1


@dataclass
class TradeProposal:
    underlying: str
    asset_class: str
    direction: str
    structure: str
    legs: list = field(default_factory=list)
    qty: int = 1
    limit_price: Optional[float] = None
    stop_pct: Optional[float] = None
    target_pct: Optional[float] = None
    max_debit: Optional[float] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    rationale: str = ""


@dataclass
class Vote:
    brain: str
    direction: str
    confidence: float
    reasoning: str = ""
    proposal: Optional[TradeProposal] = None


@dataclass
class CouncilDecision:
    symbol: str
    action: str
    confidence: float
    votes: list = field(default_factory=list)
    proposal: Optional[TradeProposal] = None
    vetoed_by: Optional[str] = None
    veto_reason: Optional[str] = None
    summary: str = ""
