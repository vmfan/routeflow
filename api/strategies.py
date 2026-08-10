from abc import ABC, abstractmethod
from .models import StrategyResult, StrategyComparison
from copy import deepcopy
from .simulation import depletebook, evolvepool
from .instrumentation import LatencyTracker, FreshnessTracker, HYBRID_SOURCES


class BaseStrategy(ABC):
    @abstractmethod
    def execute(self, symbol: str, side: str, size: float, snapshot, pool) -> StrategyResult:
        raise NotImplementedError


class NaiveStrategy(BaseStrategy):
    def __init__(self, router):
        self.router = router

    def execute(self, symbol: str, side: str, size: float, snapshot, pool) -> StrategyResult:
        route = self.router.find_best_route(
            snapshot,
            pool,
            size,
            side,
            enable_split=False,
        )

        is_buy = side.lower() == "buy"
        best_venue = (getattr(route, "best_venue", None) or "")
        best_venue_str = str(best_venue).lower()

        if hasattr(best_venue, "name"):
            best_venue_str = best_venue.name.lower()

        cex_allocation = 1.0 if best_venue_str == "binance" else 0.0
        dex_allocation = 1.0 if best_venue_str == "uniswap" else 0.0

        total_cost = (
            route.total_cost
            if is_buy and getattr(route, "total_cost", None) is not None
            else getattr(route, "net_proceeds", 0.0)
        )
        cost_per_unit = (
            route.effective_cost
            if is_buy and getattr(route, "effective_cost", None) is not None
            else getattr(route, "effective_proceeds", getattr(route, "net_proceeds", 0.0))
        )

        if not is_buy and cost_per_unit is None:
            cost_per_unit = getattr(route, "effective_proceeds", route.effective_proceeds)

        price_impact_avg = route.slippage_pct if route.slippage_pct is not None else 0.0

        return StrategyResult(
            strategyname="naive",
            totalcost=float(total_cost),
            costperunit=float(cost_per_unit),
            cexallocation=cex_allocation,
            dexallocation=dex_allocation,
            nchunks=1,
            splitratio=cex_allocation,
            priceimpactavg=float(price_impact_avg),
            partialfill=False,
        )


class ChunkedStrategy(BaseStrategy):
    def __init__(self, router, nchunks: int, venue: str | None = None):
        self.router = router
        self.nchunks = nchunks
        self.venue = venue

    def _resolve_venue(self, naive_route) -> str:
        if self.venue:
            return self.venue.lower()

        best_venue = getattr(naive_route, "best_venue", None)
        if hasattr(best_venue, "name"):
            return best_venue.name.lower()

        return str(best_venue).lower()
    
    def _chunk_size(self, size: float) -> float:
        if self.nchunks <= 0:
            raise ValueError("nchunks must be greater than zero.")
        return size / float(self.nchunks)

    def execute(self, symbol: str, side: str, size: float, snapshot, pool) -> StrategyResult:
        naive_route = self.router.find_best_route(
            snapshot,
            pool,
            size,
            side,
            enable_split=False,
        )

        venue = self._resolve_venue(naive_route)
        chunk_size = self._chunk_size(size)
        is_buy = side.lower() == "buy"

        working_book = deepcopy(snapshot)
        working_pool = deepcopy(pool)

        total_cost = 0.0
        total_price_impact = 0.0
        partial_fill = False

        for _ in range(self.nchunks):
            route = self.router.find_best_route(
                working_book,
                working_pool,
                chunk_size,
                side,
                enable_split=False,
            )

            if venue == "binance":
                breakdown = route.binance
                fill_value = breakdown.input_amount
                working_book = depletebook(
                    working_book,
                    {
                        "side": side.lower(),
                        "filled_size": chunk_size,
                    },
                )
            elif venue == "uniswap":
                breakdown = route.uniswap
                amount_in = getattr(breakdown, "amount_in", 0.0)
                amount_out = getattr(breakdown, "amount_out", 0.0)

                trade_direction = "a_to_b" if side.lower() == "sell" else "b_to_a"
                working_pool = evolvepool(
                    {
                        **deepcopy(working_pool),
                        "trade_direction": trade_direction,
                    },
                    amountin=float(amount_in),
                    amountout=float(amount_out),
                )
            else:
                raise ValueError(f"Unsupported chunked venue: {venue}")

            if venue == "binance":
                if is_buy:
                    chunk_total = breakdown.net_cost
                else:
                    chunk_total = breakdown.net_proceeds
            else:
                if is_buy:
                    chunk_total = breakdown.net_cost
                else:
                    chunk_total = breakdown.net_proceeds

            if chunk_total is None:
                partial_fill = True
                chunk_total = 0.0

            total_cost += float(chunk_total)
            total_price_impact += float(getattr(breakdown, "slippage_pct", 0.0))

        avg_price_impact = total_price_impact / float(self.nchunks)

        if is_buy:
            cost_per_unit = total_cost / float(size)
        else:
            cost_per_unit = total_cost / float(size)

        cex_allocation = 1.0 if venue == "binance" else 0.0
        dex_allocation = 1.0 if venue == "uniswap" else 0.0

        return StrategyResult(
            strategyname=f"chunked{self.nchunks}",
            totalcost=float(total_cost),
            costperunit=float(cost_per_unit),
            cexallocation=cex_allocation,
            dexallocation=dex_allocation,
            nchunks=self.nchunks,
            splitratio=cex_allocation,
            priceimpactavg=float(avg_price_impact),
            partialfill=partial_fill,
        )


class SplitStrategy(BaseStrategy):
    def __init__(self, router):
        self.router = router

    def execute(self, symbol: str, side: str, size: float, snapshot, pool) -> StrategyResult:
        route = self.router.find_best_route(
            snapshot,
            pool,
            size,
            side,
            enable_split=True,
        )

        split = getattr(route, "split", None)
        if split is None:
            raise ValueError("SplitStrategy expected route.split to be populated.")

        is_buy = side.lower() == "buy"

        binance_leg = getattr(split, "binance_leg", None)
        uniswap_leg = getattr(split, "uniswap_leg", None)

        cex_allocation = 0.0
        dex_allocation = 0.0

        if binance_leg is not None and getattr(binance_leg, "is_used", False):
            cex_allocation = float(getattr(binance_leg, "ratio", 0.0))

        if uniswap_leg is not None and getattr(uniswap_leg, "is_used", False):
            dex_allocation = float(getattr(uniswap_leg, "ratio", 0.0))

        total_cost = (
            split.total_cost
            if is_buy and getattr(split, "total_cost", None) is not None
            else getattr(split, "net_proceeds", 0.0)
        )
        cost_per_unit = (
            split.effective_cost
            if is_buy and getattr(split, "effective_cost", None) is not None
            else getattr(split, "effective_proceeds", getattr(split, "net_proceeds", 0.0))
        )

        cost_per_unit = (
            getattr(split, "unit_cost", None)
            if is_buy
            else getattr(split, "effective_proceeds", None)
        )
        if is_buy and cost_per_unit is None:
            cost_per_unit = getattr(split, "effective_cost", None)

        price_impact_avg = getattr(split, "slippage_pct", 0.0)
        partial_fill = bool(getattr(split, "partialfill", False))

        return StrategyResult(
            strategyname="split",
            totalcost=float(total_cost),
            costperunit=float(cost_per_unit if cost_per_unit is not None else 0.0),
            cexallocation=cex_allocation,
            dexallocation=dex_allocation,
            nchunks=1,
            splitratio=cex_allocation,
            priceimpactavg=float(price_impact_avg if price_impact_avg is not None else 0.0),
            partialfill=partial_fill,
        )
    

def _select_best_strategy(results: list[StrategyResult]) -> str:
    if not results:
        return ""
    return min(results, key=lambda result: result.costperunit).strategyname


def _timing_row(record):
    return {
        "run_id": record.run_id,
        "symbol": record.symbol,
        "side": record.side,
        "size": record.size,
        "strategy": record.strategy,
        "parse_ms": record.parse_ms,
        "compute_ms": record.compute_ms,
        "total_ms": record.total_ms,
        "data_age_ms": record.data_age_ms,
        "breached_target": record.breached_target,
        "snapshot_ts": record.snapshot_ts,
    }


def comparestrategies(
    symbol: str,
    side: str,
    size: float,
    snapshot,
    pool,
    router,
    runid: str | None = None,
    snapshot_ts: str | None = None,
    latency_tracker: LatencyTracker | None = None,
    freshness_tracker: FreshnessTracker | None = None,
) -> tuple[StrategyComparison, list[dict[str, object]]]:
    effective_runid = runid or f"comparison-{symbol.lower()}-{side.lower()}-{size}"
    resolved_snapshot_ts = snapshot_ts or (
        "fixture-snapshot"
        if getattr(router, "is_fixture_router", False)
        else effective_runid
    )
    timing_rows: list[dict[str, object]] = []
    data_age_ms = None
    if freshness_tracker is not None:
        data_age_ms = freshness_tracker.assert_not_stale(symbol, sources=HYBRID_SOURCES)

    if latency_tracker is not None:
        naive, naive_latency = latency_tracker.time_pipeline(
            run_id=effective_runid,
            symbol=symbol,
            side=side,
            size=size,
            strategy="naive",
            data_age_ms=data_age_ms,
            snapshot_ts=resolved_snapshot_ts,
            parse_and_update=lambda: None,
            compute_route=lambda: NaiveStrategy(router).execute(
                symbol=symbol,
                side=side,
                size=size,
                snapshot=deepcopy(snapshot),
                pool=deepcopy(pool),
            ),
        )
        timing_rows.append(_timing_row(naive_latency))
    else:
        naive = NaiveStrategy(router).execute(
            symbol=symbol,
            side=side,
            size=size,
            snapshot=deepcopy(snapshot),
            pool=deepcopy(pool),
        )

    if latency_tracker is not None:
        chunked2, chunked2_latency = latency_tracker.time_pipeline(
            run_id=effective_runid,
            symbol=symbol,
            side=side,
            size=size,
            strategy="chunked2",
            data_age_ms=data_age_ms,
            snapshot_ts=resolved_snapshot_ts,
            parse_and_update=lambda: None,
            compute_route=lambda: ChunkedStrategy(router, nchunks=2).execute(
                symbol=symbol,
                side=side,
                size=size,
                snapshot=deepcopy(snapshot),
                pool=deepcopy(pool),
            ),
        )
        timing_rows.append(_timing_row(chunked2_latency))
    else:
        chunked2 = ChunkedStrategy(router, nchunks=2).execute(
            symbol=symbol,
            side=side,
            size=size,
            snapshot=deepcopy(snapshot),
            pool=deepcopy(pool),
        )

    if latency_tracker is not None:
        chunked5, chunked5_latency = latency_tracker.time_pipeline(
            run_id=effective_runid,
            symbol=symbol,
            side=side,
            size=size,
            strategy="chunked5",
            data_age_ms=data_age_ms,
            snapshot_ts=resolved_snapshot_ts,
            parse_and_update=lambda: None,
            compute_route=lambda: ChunkedStrategy(router, nchunks=5).execute(
                symbol=symbol,
                side=side,
                size=size,
                snapshot=deepcopy(snapshot),
                pool=deepcopy(pool),
            ),
        )
        timing_rows.append(_timing_row(chunked5_latency))
    else:
        chunked5 = ChunkedStrategy(router, nchunks=5).execute(
            symbol=symbol,
            side=side,
            size=size,
            snapshot=deepcopy(snapshot),
            pool=deepcopy(pool),
        )

    if latency_tracker is not None:
        chunked10, chunked10_latency = latency_tracker.time_pipeline(
            run_id=effective_runid,
            symbol=symbol,
            side=side,
            size=size,
            strategy="chunked10",
            data_age_ms=data_age_ms,
            snapshot_ts=resolved_snapshot_ts,
            parse_and_update=lambda: None,
            compute_route=lambda: ChunkedStrategy(router, nchunks=10).execute(
                symbol=symbol,
                side=side,
                size=size,
                snapshot=deepcopy(snapshot),
                pool=deepcopy(pool),
            ),
        )
        timing_rows.append(_timing_row(chunked10_latency))
    else:
        chunked10 = ChunkedStrategy(router, nchunks=10).execute(
            symbol=symbol,
            side=side,
            size=size,
            snapshot=deepcopy(snapshot),
            pool=deepcopy(pool),
        )

    if latency_tracker is not None:
        split, split_latency = latency_tracker.time_pipeline(
            run_id=effective_runid,
            symbol=symbol,
            side=side,
            size=size,
            strategy="split",
            data_age_ms=data_age_ms,
            snapshot_ts=resolved_snapshot_ts,
            parse_and_update=lambda: None,
            compute_route=lambda: SplitStrategy(router).execute(
                symbol=symbol,
                side=side,
                size=size,
                snapshot=deepcopy(snapshot),
                pool=deepcopy(pool),
            ),
        )
        timing_rows.append(_timing_row(split_latency))
    else:
        split = SplitStrategy(router).execute(
            symbol=symbol,
            side=side,
            size=size,
            snapshot=deepcopy(snapshot),
            pool=deepcopy(pool),
        )

    results = [naive, chunked2, chunked5, chunked10, split]

    comparison = StrategyComparison(
        symbol=symbol,
        side=side,
        size=size,
        snapshotts=resolved_snapshot_ts,
        results=results,
        beststrategy=_select_best_strategy(results),
        naivecostcpu=naive.costperunit,
    )

    return comparison, timing_rows


def _assert_fresh_enough(freshness_tracker, symbol):
    return freshness_tracker.assert_not_stale(
        symbol,
        sources=HYBRID_SOURCES,
    )


def _run_timed_strategy(
    *,
    symbol,
    side,
    size,
    strategy,
    runid,
    snapshot_ts,
    latency_tracker,
    freshness_tracker,
    compute_route,
):
    data_age_ms = freshness_tracker.effective_data_age_ms(
        symbol,
        HYBRID_SOURCES,
    )
    _assert_fresh_enough(freshness_tracker, symbol)

    result, record = latency_tracker.time_pipeline(
        run_id=runid,
        symbol=symbol,
        side=side,
        size=size,
        strategy=strategy,
        data_age_ms=data_age_ms,
        snapshot_ts=snapshot_ts,
        parse_and_update=lambda: None,
        compute_route=compute_route,
    )
    return result, _timing_row(record)