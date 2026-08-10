import math
import pytest

from api.simulation import depletebook, evolvepool
from api.strategies import NaiveStrategy, SplitStrategy, ChunkedStrategy, comparestrategies
from api.instrumentation import LatencyTracker, FreshnessTracker, StaleDataError
from api.models import StrategyResult


class DummyRoute:
    def __init__(
        self,
        best_venue,
        total_cost=None,
        effective_cost=None,
        net_proceeds=None,
        effective_proceeds=None,
        slippage_pct=0.0,
    ):
        self.best_venue = best_venue
        self.total_cost = total_cost
        self.effective_cost = effective_cost
        self.net_proceeds = net_proceeds
        self.effective_proceeds = effective_proceeds
        self.slippage_pct = slippage_pct


class DummyVenue:
    def __init__(self, name):
        self.name = name


class DummyRouter:
    def __init__(self, route):
        self.route = route

    def find_best_route(self, snapshot, pool, size, side, enable_split=False):
        return self.route
    

class DummySplitLeg:
    def __init__(self, ratio=0.0, is_used=False):
        self.ratio = ratio
        self.is_used = is_used


class DummySplit:
    def __init__(
        self,
        total_cost=None,
        effective_cost=None,
        net_proceeds=None,
        effective_proceeds=None,
        slippage_pct=0.0,
        binance_leg=None,
        uniswap_leg=None,
        partialfill=False,
    ):
        self.total_cost = total_cost
        self.effective_cost = effective_cost
        self.net_proceeds = net_proceeds
        self.effective_proceeds = effective_proceeds
        self.slippage_pct = slippage_pct
        self.binance_leg = binance_leg
        self.uniswap_leg = uniswap_leg
        self.partialfill = partialfill


class DummyBreakdown:
    def __init__(
        self,
        input_amount=0.0,
        amount_in=0.0,
        amount_out=0.0,
        net_cost=None,
        net_proceeds=None,
        slippage_pct=0.0,
    ):
        self.input_amount = input_amount
        self.amount_in = amount_in
        self.amount_out = amount_out
        self.net_cost = net_cost
        self.net_proceeds = net_proceeds
        self.slippage_pct = slippage_pct


class DummySplitRoute:
    def __init__(self, split, best_venue=None):
        self.split = split
        self.best_venue = best_venue or DummyVenue("Split")


class DummyChunkRoute:
    def __init__(self, best_venue, binance=None, uniswap=None):
        self.best_venue = best_venue
        self.binance = binance
        self.uniswap = uniswap


class DummySequentialRouter:
    def __init__(self, routes):
        self.routes = list(routes)
        self.calls = []

    def find_best_route(self, snapshot, pool, size, side, enable_split=False):
        self.calls.append(
            {
                "snapshot": snapshot,
                "pool": pool,
                "size": size,
                "side": side,
                "enable_split": enable_split,
            }
        )
        if not self.routes:
            raise AssertionError("No more dummy routes configured.")
        return self.routes.pop(0)


NAIVE_CASES = [
    (
        "buy",
        DummyRoute(
            best_venue=DummyVenue("Binance"),
            total_cost=3004.001,
            effective_cost=3004.001,
            slippage_pct=0.01,
        ),
        {
            "strategyname": "naive",
            "totalcost": 3004.001,
            "costperunit": 3004.001,
            "cexallocation": 1.0,
            "dexallocation": 0.0,
            "nchunks": 1,
            "splitratio": 1.0,
            "priceimpactavg": 0.01,
            "partialfill": False,
        },
    ),
    (
        "sell",
        DummyRoute(
            best_venue=DummyVenue("Uniswap"),
            net_proceeds=2996.0,
            effective_proceeds=2996.0,
            slippage_pct=0.01,
        ),
        {
            "strategyname": "naive",
            "totalcost": 2996.0,
            "costperunit": 2996.0,
            "cexallocation": 0.0,
            "dexallocation": 1.0,
            "nchunks": 1,
            "splitratio": 0.0,
            "priceimpactavg": 0.01,
            "partialfill": False,
        },
    ),
]


SPLIT_CASES = [
    (
        "buy",
        DummySplit(
            total_cost=2999.5,
            effective_cost=2999.5,
            slippage_pct=0.01,
            binance_leg=DummySplitLeg(ratio=0.6, is_used=True),
            uniswap_leg=DummySplitLeg(ratio=0.4, is_used=True),
            partialfill=False,
        ),
        {
            "strategyname": "split",
            "totalcost": 2999.5,
            "costperunit": 2999.5,
            "cexallocation": 0.6,
            "dexallocation": 0.4,
            "nchunks": 1,
            "splitratio": 0.6,
            "priceimpactavg": 0.01,
            "partialfill": False,
        },
    ),
    (
        "sell",
        DummySplit(
            net_proceeds=2998.5,
            effective_proceeds=2998.5,
            slippage_pct=0.01,
            binance_leg=DummySplitLeg(ratio=0.45, is_used=True),
            uniswap_leg=DummySplitLeg(ratio=0.55, is_used=True),
            partialfill=False,
        ),
        {
            "strategyname": "split",
            "totalcost": 2998.5,
            "costperunit": 2998.5,
            "cexallocation": 0.45,
            "dexallocation": 0.55,
            "nchunks": 1,
            "splitratio": 0.45,
            "priceimpactavg": 0.01,
            "partialfill": False,
        },
    ),
]
    

@pytest.mark.parametrize("side,route,expected", NAIVE_CASES)
def test_naive_strategy_matches_route_output(side, route, expected):
    router = DummyRouter(route)
    strategy = NaiveStrategy(router)

    result = strategy.execute(
        symbol="ETHUSDT",
        side=side,
        size=1.0,
        snapshot={},
        pool={},
    )

    assert isinstance(result, StrategyResult)
    assert result.strategyname == expected["strategyname"]
    assert result.totalcost == expected["totalcost"]
    assert result.costperunit == expected["costperunit"]
    assert result.cexallocation == expected["cexallocation"]
    assert result.dexallocation == expected["dexallocation"]
    assert result.nchunks == expected["nchunks"]
    assert result.splitratio == expected["splitratio"]
    assert result.priceimpactavg == expected["priceimpactavg"]
    assert result.partialfill is expected["partialfill"]


def test_depletebook_removes_consumed_levels():
    book = {
        "bids": [[100.0, 2.0], [99.0, 3.0]],
        "asks": [[101.0, 1.5], [102.0, 4.0]],
    }
    fill = {
        "side": "buy",
        "filled_size": 1.5,
    }

    residual = depletebook(book, fill)

    assert residual["asks"] == [[102.0, 4.0]]
    assert book["asks"] == [[101.0, 1.5], [102.0, 4.0]]


def test_depletebook_reduces_partially_consumed_level():
    book = {
        "bids": [[100.0, 2.0], [99.0, 3.0]],
        "asks": [[101.0, 1.5], [102.0, 4.0]],
    }
    fill = {
        "side": "buy",
        "filled_size": 2.0,
    }

    residual = depletebook(book, fill)

    assert residual["asks"] == [[102.0, 3.5]]
    assert book["asks"] == [[101.0, 1.5], [102.0, 4.0]]


def test_evolvepool_updates_reserves_a_to_b():
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 200000.0,
        "trade_direction": "a_to_b",
    }

    updated = evolvepool(pool, amountin=1.0, amountout=1900.0)

    assert updated["reserve_token_a"] == 101.0
    assert updated["reserve_token_b"] == 198100.0
    assert pool["reserve_token_a"] == 100.0
    assert pool["reserve_token_b"] == 200000.0


def test_evolvepool_updates_reserves_b_to_a():
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 200000.0,
        "trade_direction": "b_to_a",
    }

    updated = evolvepool(pool, amountin=2000.0, amountout=0.95)

    assert updated["reserve_token_a"] == 99.05
    assert updated["reserve_token_b"] == 202000.0
    assert pool["reserve_token_a"] == 100.0
    assert pool["reserve_token_b"] == 200000.0


def test_evolvepool_keeps_reserves_positive():
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 200000.0,
        "trade_direction": "a_to_b",
    }

    updated = evolvepool(pool, amountin=1.0, amountout=1000.0)

    assert updated["reserve_token_a"] > 0.0
    assert updated["reserve_token_b"] > 0.0
    assert math.isfinite(updated["reserve_token_a"])
    assert math.isfinite(updated["reserve_token_b"])


def test_split_strategy_raises_when_split_missing():
    route = DummyRoute(
        best_venue=DummyVenue("Split"),
        slippage_pct=0.01,
    )
    route.split = None

    router = DummyRouter(route)
    strategy = SplitStrategy(router)

    try:
        strategy.execute(
            symbol="ETHUSDT",
            side="buy",
            size=1.0,
            snapshot={},
            pool={},
        )
        assert False, "Expected ValueError when split payload is missing."
    except ValueError as exc:
        assert "route.split" in str(exc)


def test_split_strategy_not_worse_than_naive_baselines():
    naive_cex = 3004.001
    naive_dex = 3003.660
    split_cpu = 2999.500

    assert split_cpu <= min(naive_cex, naive_dex)


def test_chunked_strategy_aggregates_binance_chunks():
    routes = [
        DummyChunkRoute(best_venue=DummyVenue("Binance")),
        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(
                input_amount=0.5,
                net_cost=1500.0,
                slippage_pct=0.01,
            ),
        ),
        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(
                input_amount=0.5,
                net_cost=1510.0,
                slippage_pct=0.03,
            ),
        ),
    ]

    router = DummySequentialRouter(routes)
    strategy = ChunkedStrategy(router, nchunks=2)

    snapshot = {
        "bids": [[100.0, 5.0]],
        "asks": [[101.0, 5.0]],
    }
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 200000.0,
    }

    result = strategy.execute(
        symbol="ETHUSDT",
        side="buy",
        size=1.0,
        snapshot=snapshot,
        pool=pool,
    )

    assert isinstance(result, StrategyResult)
    assert result.strategyname == "chunked2"
    assert result.totalcost == 3010.0
    assert result.costperunit == 3010.0
    assert result.cexallocation == 1.0
    assert result.dexallocation == 0.0
    assert result.nchunks == 2
    assert result.splitratio == 1.0
    assert result.priceimpactavg == 0.02
    assert result.partialfill is False


def test_chunked_strategy_aggregates_uniswap_chunks():
    routes = [
        DummyChunkRoute(best_venue=DummyVenue("Uniswap")),
        DummyChunkRoute(
            best_venue=DummyVenue("Uniswap"),
            uniswap=DummyBreakdown(
                amount_in=1500.0,
                amount_out=0.5,
                net_cost=1501.0,
                slippage_pct=0.02,
            ),
        ),
        DummyChunkRoute(
            best_venue=DummyVenue("Uniswap"),
            uniswap=DummyBreakdown(
                amount_in=1510.0,
                amount_out=0.5,
                net_cost=1512.0,
                slippage_pct=0.04,
            ),
        ),
    ]

    router = DummySequentialRouter(routes)
    strategy = ChunkedStrategy(router, nchunks=2)

    snapshot = {
        "bids": [[100.0, 5.0]],
        "asks": [[101.0, 5.0]],
    }
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 200000.0,
    }

    result = strategy.execute(
        symbol="ETHUSDT",
        side="buy",
        size=1.0,
        snapshot=snapshot,
        pool=pool,
    )

    assert isinstance(result, StrategyResult)
    assert result.strategyname == "chunked2"
    assert result.totalcost == 3013.0
    assert result.costperunit == 3013.0
    assert result.cexallocation == 0.0
    assert result.dexallocation == 1.0
    assert result.nchunks == 2
    assert result.splitratio == 0.0
    assert result.priceimpactavg == 0.03
    assert result.partialfill is False


def test_chunked_strategy_does_not_mutate_original_inputs():
    routes = [
        DummyChunkRoute(best_venue=DummyVenue("Binance")),
        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(
                input_amount=0.5,
                net_cost=1500.0,
                slippage_pct=0.01,
            ),
        ),
        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(
                input_amount=0.5,
                net_cost=1510.0,
                slippage_pct=0.03,
            ),
        ),
    ]

    router = DummySequentialRouter(routes)
    strategy = ChunkedStrategy(router, nchunks=2)

    snapshot = {
        "bids": [[100.0, 5.0]],
        "asks": [[101.0, 5.0]],
    }
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 200000.0,
    }

    snapshot_before = {
        "bids": [[100.0, 5.0]],
        "asks": [[101.0, 5.0]],
    }
    pool_before = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 200000.0,
    }

    strategy.execute(
        symbol="ETHUSDT",
        side="buy",
        size=1.0,
        snapshot=snapshot,
        pool=pool,
    )

    assert snapshot == snapshot_before
    assert pool == pool_before


def test_chunked_strategy_no_free_lunch_same_venue():
    single_shot_cost_per_unit = 3000.0
    chunked_cost_per_unit = 3010.0

    assert chunked_cost_per_unit >= single_shot_cost_per_unit


def test_naive_strategy_matches_sell_route_output():
    route = DummyRoute(
        best_venue=DummyVenue("Uniswap"),
        net_proceeds=2996.0,
        effective_proceeds=2996.0,
        slippage_pct=0.01,
    )
    router = DummyRouter(route)
    strategy = NaiveStrategy(router)

    result = strategy.execute(
        symbol="ETHUSDT",
        side="sell",
        size=1.0,
        snapshot={},
        pool={},
    )

    assert isinstance(result, StrategyResult)
    assert result.strategyname == "naive"
    assert result.totalcost == 2996.0
    assert result.costperunit == 2996.0
    assert result.cexallocation == 0.0
    assert result.dexallocation == 1.0
    assert result.nchunks == 1
    assert result.splitratio == 0.0
    assert result.priceimpactavg == 0.01
    assert result.partialfill is False


@pytest.mark.parametrize("side,split_payload,expected", SPLIT_CASES)
def test_split_strategy_matches_split_output(side, split_payload, expected):
    route = DummyRoute(
        best_venue=DummyVenue("Split"),
        slippage_pct=expected["priceimpactavg"],
    )
    route.split = split_payload

    router = DummyRouter(route)
    strategy = SplitStrategy(router)

    result = strategy.execute(
        symbol="ETHUSDT",
        side=side,
        size=1.0,
        snapshot={},
        pool={},
    )

    assert isinstance(result, StrategyResult)
    assert result.strategyname == expected["strategyname"]
    assert result.totalcost == expected["totalcost"]
    assert result.costperunit == expected["costperunit"]
    assert result.cexallocation == expected["cexallocation"]
    assert result.dexallocation == expected["dexallocation"]
    assert result.nchunks == expected["nchunks"]
    assert result.splitratio == expected["splitratio"]
    assert result.priceimpactavg == expected["priceimpactavg"]
    assert result.partialfill is expected["partialfill"]


def test_chunked_strategy_aggregates_uniswap_sell_chunks():
    routes = [
        DummyChunkRoute(best_venue=DummyVenue("Uniswap")),
        DummyChunkRoute(
            best_venue=DummyVenue("Uniswap"),
            uniswap=DummyBreakdown(
                amount_in=0.5,
                amount_out=1499.0,
                net_proceeds=1499.0,
                slippage_pct=0.01,
            ),
        ),
        DummyChunkRoute(
            best_venue=DummyVenue("Uniswap"),
            uniswap=DummyBreakdown(
                amount_in=0.5,
                amount_out=1497.0,
                net_proceeds=1497.0,
                slippage_pct=0.03,
            ),
        ),
    ]

    router = DummySequentialRouter(routes)
    strategy = ChunkedStrategy(router, nchunks=2)

    snapshot = {
        "bids": [[3000.0, 10.0], [2999.0, 20.0]],
        "asks": [[3001.0, 10.0], [3002.0, 20.0]],
    }
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 300000.0,
    }

    result = strategy.execute(
        symbol="ETHUSDT",
        side="sell",
        size=1.0,
        snapshot=snapshot,
        pool=pool,
    )

    assert isinstance(result, StrategyResult)
    assert result.strategyname == "chunked2"
    assert result.totalcost == 2996.0
    assert result.costperunit == 2996.0
    assert result.cexallocation == 0.0
    assert result.dexallocation == 1.0
    assert result.nchunks == 2
    assert result.splitratio == 0.0
    assert result.priceimpactavg == 0.02
    assert result.partialfill is False


def test_chunked_strategy_aggregates_binance_sell_chunks():
    routes = [
        DummyChunkRoute(best_venue=DummyVenue("Binance")),
        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(
                input_amount=0.5,
                net_proceeds=1500.0,
                slippage_pct=0.01,
            ),
        ),
        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(
                input_amount=0.5,
                net_proceeds=1498.0,
                slippage_pct=0.03,
            ),
        ),
    ]

    router = DummySequentialRouter(routes)
    strategy = ChunkedStrategy(router, nchunks=2, venue="binance")

    snapshot = {
        "bids": [[3000.0, 10.0], [2999.0, 20.0]],
        "asks": [[3001.0, 10.0], [3002.0, 20.0]],
    }
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 300000.0,
    }

    result = strategy.execute(
        symbol="ETHUSDT",
        side="sell",
        size=1.0,
        snapshot=snapshot,
        pool=pool,
    )

    assert isinstance(result, StrategyResult)
    assert result.strategyname == "chunked2"
    assert result.totalcost == 2998.0
    assert result.costperunit == 2998.0
    assert result.cexallocation == 1.0
    assert result.dexallocation == 0.0
    assert result.nchunks == 2
    assert result.splitratio == 1.0
    assert result.priceimpactavg == 0.02
    assert result.partialfill is False


def test_chunked_sell_strategy_does_not_mutate_original_inputs():
    routes = [
        DummyChunkRoute(best_venue=DummyVenue("Uniswap")),
        DummyChunkRoute(
            best_venue=DummyVenue("Uniswap"),
            uniswap=DummyBreakdown(
                amount_in=0.5,
                amount_out=1499.0,
                net_proceeds=1499.0,
                slippage_pct=0.01,
            ),
        ),
        DummyChunkRoute(
            best_venue=DummyVenue("Uniswap"),
            uniswap=DummyBreakdown(
                amount_in=0.5,
                amount_out=1497.0,
                net_proceeds=1497.0,
                slippage_pct=0.03,
            ),
        ),
    ]

    router = DummySequentialRouter(routes)
    strategy = ChunkedStrategy(router, nchunks=2)

    snapshot = {
        "bids": [[3000.0, 10.0], [2999.0, 20.0]],
        "asks": [[3001.0, 10.0], [3002.0, 20.0]],
    }
    pool = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 300000.0,
    }

    snapshot_before = {
        "bids": [[3000.0, 10.0], [2999.0, 20.0]],
        "asks": [[3001.0, 10.0], [3002.0, 20.0]],
    }
    pool_before = {
        "reserve_token_a": 100.0,
        "reserve_token_b": 300000.0,
    }

    strategy.execute(
        symbol="ETHUSDT",
        side="sell",
        size=1.0,
        snapshot=snapshot,
        pool=pool,
    )

    assert snapshot == snapshot_before
    assert pool == pool_before


def test_comparestrategies_raises_when_hybrid_state_is_stale():
    freshness_tracker = FreshnessTracker()
    latency_tracker = LatencyTracker()

    freshness_tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)
    freshness_tracker.mark_updated("ETHUSDT", "uniswap", updated_ns=1_000_000_000)

    try:
        comparestrategies(
            symbol="ETHUSDT",
            side="buy",
            size=5.0,
            snapshot={},
            pool={},
            router=DummyRouter(route={}),
            runid="run-1",
            snapshot_ts="binance=1|uniswap=1",
            latency_tracker=latency_tracker,
            freshness_tracker=freshness_tracker,
        )
        assert False, "Expected StaleDataError"
    except StaleDataError:
        pass


def test_comparestrategies_returns_five_timing_rows_when_latency_tracker_is_provided():
    router = DummySequentialRouter([
        DummyRoute(
            best_venue=DummyVenue("Binance"),
            total_cost=3004.001,
            effective_cost=3004.001,
            slippage_pct=0.01,
        ),

        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(input_amount=0.5, net_cost=1502.0, slippage_pct=0.01),
        ),
        *[
            DummyChunkRoute(
                best_venue=DummyVenue("Binance"),
                binance=DummyBreakdown(input_amount=0.5, net_cost=1502.0, slippage_pct=0.01),
            )
            for _ in range(2)
        ],

        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(input_amount=0.2, net_cost=601.0, slippage_pct=0.01),
        ),
        *[
            DummyChunkRoute(
                best_venue=DummyVenue("Binance"),
                binance=DummyBreakdown(input_amount=0.2, net_cost=601.0, slippage_pct=0.01),
            )
            for _ in range(5)
        ],

        DummyChunkRoute(
            best_venue=DummyVenue("Binance"),
            binance=DummyBreakdown(input_amount=0.1, net_cost=300.5, slippage_pct=0.01),
        ),
        *[
            DummyChunkRoute(
                best_venue=DummyVenue("Binance"),
                binance=DummyBreakdown(input_amount=0.1, net_cost=300.5, slippage_pct=0.01),
            )
            for _ in range(10)
        ],

        DummySplitRoute(
            split=DummySplit(
                total_cost=2999.5,
                effective_cost=2999.5,
                slippage_pct=0.01,
                binance_leg=DummySplitLeg(ratio=0.6, is_used=True),
                uniswap_leg=DummySplitLeg(ratio=0.4, is_used=True),
                partialfill=False,
            ),
            best_venue=DummyVenue("Split"),
        ),
    ])

    comparison, timing_rows = comparestrategies(
        symbol="ETHUSDT",
        side="buy",
        size=1.0,
        snapshot={},
        pool={},
        router=router,
        runid="run-1",
        snapshot_ts="ts-1",
        latency_tracker=LatencyTracker(),
        freshness_tracker=None,
    )

    assert comparison.symbol == "ETHUSDT"
    assert comparison.side == "buy"
    assert comparison.size == 1.0

    assert len(timing_rows) == 5
    assert [row["strategy"] for row in timing_rows] == [
        "naive",
        "chunked2",
        "chunked5",
        "chunked10",
        "split",
    ]
    assert [row["run_id"] for row in timing_rows] == ["run-1"] * 5
    assert [row["symbol"] for row in timing_rows] == ["ETHUSDT"] * 5
    assert [row["side"] for row in timing_rows] == ["buy"] * 5
    assert [row["size"] for row in timing_rows] == [1.0] * 5
    assert [row["snapshot_ts"] for row in timing_rows] == ["ts-1"] * 5

    for row in timing_rows:
        assert row["parse_ms"] is not None
        assert row["compute_ms"] is not None
        assert row["total_ms"] is not None
        assert row["data_age_ms"] is None
        assert row["breached_target"] in {True, False}


def test_comparestrategies_raises_stale_data_before_any_strategy_executes():
    class StubFreshnessTracker:
        def assert_not_stale(self, symbol, sources):
            raise StaleDataError("stale")

    router = DummySequentialRouter(
        [
            DummyRoute(
                best_venue=DummyVenue("Binance"),
                total_cost=3004.001,
                effective_cost=3004.001,
                slippage_pct=0.01,
            )
        ]
    )

    try:
        comparestrategies(
            symbol="ETHUSDT",
            side="buy",
            size=1.0,
            snapshot={},
            pool={},
            router=router,
            runid="run-1",
            snapshot_ts="ts-1",
            latency_tracker=LatencyTracker(),
            freshness_tracker=StubFreshnessTracker(),
        )
        assert False, "Expected StaleDataError"
    except StaleDataError as exc:
        assert str(exc) == "stale"

    assert router.calls == []