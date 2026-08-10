from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Callable


LATENCY_TARGET_MS = 100.0
FRESHNESS_WARNING_MS = 1_000.0
FRESHNESS_CRITICAL_MS = 3_000.0
HYBRID_SOURCES = ["binance", "uniswap"]


@dataclass
class LatencyRecord:
    run_id: str
    symbol: str
    msg_received_ns: int
    cache_updated_ns: int | None = None
    route_complete_ns: int | None = None
    parse_ms: float | None = None
    compute_ms: float | None = None
    total_ms: float | None = None
    breached_target: bool = False
    side: str | None = None
    size: float | None = None
    strategy: str | None = None
    data_age_ms: float | None = None
    snapshot_ts: str | None = None

    def finalize(self) -> None:
        if self.cache_updated_ns is not None:
            self.parse_ms = (self.cache_updated_ns - self.msg_received_ns) / 1_000_000

        if self.cache_updated_ns is not None and self.route_complete_ns is not None:
            self.compute_ms = (self.route_complete_ns - self.cache_updated_ns) / 1_000_000

        if self.route_complete_ns is not None:
            self.total_ms = (self.route_complete_ns - self.msg_received_ns) / 1_000_000

        self.breached_target = (
            self.total_ms is not None and self.total_ms > LATENCY_TARGET_MS
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    

class LatencyBuffer:
    def __init__(self, maxlen: int = 10_000) -> None:
        self._records: deque[LatencyRecord] = deque(maxlen=maxlen)

    def append(self, record: LatencyRecord) -> None:
        self._records.append(record)

    def to_list(self) -> list[LatencyRecord]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)
    

@dataclass
class LatencySummary:
    n_samples: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    breach_count: int
    breach_pct: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
    

def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0

    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (len(sorted_values) - 1) * pct
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    weight = rank - lower_index

    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    return lower_value + (upper_value - lower_value) * weight


def compute_summary(records: list[LatencyRecord]) -> LatencySummary:
    totals = sorted(
        record.total_ms for record in records if record.total_ms is not None
    )

    if not totals:
        return LatencySummary(
            n_samples=0,
            p50_ms=0.0,
            p95_ms=0.0,
            p99_ms=0.0,
            min_ms=0.0,
            max_ms=0.0,
            mean_ms=0.0,
            breach_count=0,
            breach_pct=0.0,
        )

    breach_count = sum(
        1 for record in records if record.total_ms is not None and record.breached_target
    )

    return LatencySummary(
        n_samples=len(totals),
        p50_ms=_percentile(totals, 0.50),
        p95_ms=_percentile(totals, 0.95),
        p99_ms=_percentile(totals, 0.99),
        min_ms=min(totals),
        max_ms=max(totals),
        mean_ms=sum(totals) / len(totals),
        breach_count=breach_count,
        breach_pct=(breach_count / len(totals)) * 100.0,
    )


class LatencyTracker:
    def __init__(self, buffer: LatencyBuffer | None = None) -> None:
        self.buffer = buffer if buffer is not None else LatencyBuffer()

    def start_record(
        self,
        *,
        run_id: str,
        symbol: str,
        side: str | None = None,
        size: float | None = None,
        strategy: str | None = None,
        data_age_ms: float | None = None,
        snapshot_ts: str | None = None,
    ) -> LatencyRecord:
        return LatencyRecord(
            run_id=run_id,
            symbol=symbol,
            side=side,
            size=size,
            strategy=strategy,
            data_age_ms=data_age_ms,
            snapshot_ts=snapshot_ts,
            msg_received_ns=time.perf_counter_ns(),
        )

    def mark_cache_updated(self, record: LatencyRecord) -> None:
        record.cache_updated_ns = time.perf_counter_ns()
        record.finalize()

    def mark_route_complete(self, record: LatencyRecord) -> None:
        record.route_complete_ns = time.perf_counter_ns()
        record.finalize()

    def store(self, record: LatencyRecord) -> LatencyRecord:
        record.finalize()
        self.buffer.append(record)
        return record

    def time_pipeline(
        self,
        *,
        run_id: str,
        symbol: str,
        parse_and_update: Callable[[], Any],
        compute_route: Callable[[], Any],
        side: str | None = None,
        size: float | None = None,
        strategy: str | None = None,
        data_age_ms: float | None = None,
        snapshot_ts: str | None = None,
    ) -> tuple[Any, LatencyRecord]:
        record = self.start_record(
            run_id=run_id,
            symbol=symbol,
            side=side,
            size=size,
            strategy=strategy,
            data_age_ms=data_age_ms,
            snapshot_ts=snapshot_ts,
        )

        parse_and_update()

        try:
            self.mark_cache_updated(record)
            result = compute_route()
            self.mark_route_complete(record)
        except Exception:
            self.store(record)
            raise

        self.store(record)
        return result, record
    
    def attach_data_age(
        self,
        record: LatencyRecord,
        freshness_tracker: FreshnessTracker,
        *,
        sources: list[str],
        now_ns: int | None = None,
    ) -> None:
        record.data_age_ms = freshness_tracker.effective_data_age_ms(
            record.symbol,
            sources,
            now_ns=now_ns,
        )
    

class StaleDataError(RuntimeError):
    pass


class FreshnessTracker:
    def __init__(self) -> None:
        self._last_update_ns_by_key: dict[tuple[str, str], int] = {}

    def mark_updated(
        self,
        symbol: str,
        source: str,
        updated_ns: int | None = None,
    ) -> int:
        timestamp = updated_ns if updated_ns is not None else time.perf_counter_ns()
        self._last_update_ns_by_key[(symbol, source)] = timestamp
        return timestamp

    def last_update_ns(self, symbol: str, source: str) -> int | None:
        return self._last_update_ns_by_key.get((symbol, source))

    def data_age_ms(
        self,
        symbol: str,
        source: str,
        now_ns: int | None = None,
    ) -> float | None:
        updated_ns = self.last_update_ns(symbol, source)
        if updated_ns is None:
            return None

        current_ns = now_ns if now_ns is not None else time.perf_counter_ns()
        return (current_ns - updated_ns) / 1_000_000
    
    def source_ages_ms(
        self,
        symbol: str,
        sources: list[str],
        now_ns: int | None = None,
    ) -> dict[str, float | None]:
        return {
            source: self.data_age_ms(symbol, source, now_ns=now_ns)
            for source in sources
        }
    
    def effective_data_age_ms(
        self,
        symbol: str,
        sources: list[str],
        now_ns: int | None = None,
    ) -> float | None:
        ages = self.source_ages_ms(symbol, sources, now_ns=now_ns)
        known_ages = [age for age in ages.values() if age is not None]

        if not known_ages:
            return None

        if len(known_ages) != len(sources):
            return None

        return max(known_ages)

    def status(
        self,
        symbol: str,
        sources: list[str],
        now_ns: int | None = None,
    ) -> str | None:
        age_ms = self.effective_data_age_ms(symbol, sources, now_ns=now_ns)
        if age_ms is None:
            return None
        if age_ms > FRESHNESS_CRITICAL_MS:
            return "critical"
        if age_ms > FRESHNESS_WARNING_MS:
            return "warning"
        return "fresh"

    def assert_not_stale(
        self,
        symbol: str,
        *,
        sources: list[str],
        max_age_ms: float = FRESHNESS_CRITICAL_MS,
        now_ns: int | None = None,
    ) -> float:
        age_ms = self.effective_data_age_ms(symbol, sources, now_ns=now_ns)
        if age_ms is None:
            raise StaleDataError(
                f"No complete freshness state recorded for symbol={symbol}, sources={sources}"
            )
        if age_ms > max_age_ms:
            raise StaleDataError(
                f"Stale data for symbol={symbol}, sources={sources}: "
                f"age_ms={age_ms:.3f} exceeds max_age_ms={max_age_ms:.3f}"
            )
        return age_ms