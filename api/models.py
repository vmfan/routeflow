from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Explanation:
    decision_key: str
    title: str
    summary: str
    details: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommended_venue: Optional[str] = None
    recommended_split_ratio_binance: Optional[float] = None
    recommended_split_ratio_uniswap: Optional[float] = None


@dataclass(frozen=True)
class StrategyResult:
    strategyname: str
    totalcost: float
    costperunit: float
    cexallocation: float
    dexallocation: float
    nchunks: int
    splitratio: float
    priceimpactavg: float
    partialfill: bool


@dataclass(frozen=True)
class StrategyComparison:
    symbol: str
    side: str
    size: float
    snapshotts: str
    results: List[StrategyResult] = field(default_factory=list)
    beststrategy: str = ""
    naivecostcpu: float = 0.0


def savingspct(result: StrategyResult, comparison: StrategyComparison) -> float:
    if comparison.naivecostcpu == 0:
        return 0.0

    if comparison.side.lower() == "sell":
        return ((result.costperunit - comparison.naivecostcpu) / abs(comparison.naivecostcpu)) * 100.0

    return ((comparison.naivecostcpu - result.costperunit) / abs(comparison.naivecostcpu)) * 100.0