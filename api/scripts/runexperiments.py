import os

import redis
import json
from types import SimpleNamespace
import argparse
import csv
from pathlib import Path

from api.strategies import comparestrategies
from api.models import savingspct
from api.instrumentation import FreshnessTracker, LatencyTracker, compute_summary, HYBRID_SOURCES

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures"

CSV_COLUMNS = [
    "runid",
    "symbol",
    "side",
    "size",
    "strategy",
    "nchunks",
    "cexallocation",
    "dexallocation",
    "totalcost",
    "costperunit",
    "vsnaivesavingspct",
    "priceimpactavg",
    "splitratio",
    "partialfill",
    "snapshotts",
]


TIMING_CSV_COLUMNS = [
    "run_id",
    "symbol",
    "side",
    "size",
    "strategy",
    "parse_ms",
    "compute_ms",
    "total_ms",
    "data_age_ms",
    "breached_target",
    "snapshot_ts",
]


SIZE_GRID = [1.0, 5.0, 10.0, 25.0, 50.0, 100.0]

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True,
)

BENCHMARK_ITERATIONS = 1_000
BENCHMARK_BASELINE_PATH = Path(__file__).resolve().parents[2] / "results/benchmark_baseline.json"

LIVE_BINANCE_REDIS_KEY = "orderbook:binance:{symbol}"
LIVE_UNISWAP_REDIS_KEY = "orderbook:uniswapv2:{symbol}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Order splitting experiment harness")
    parser.add_argument("--symbol", required=True, help="Trading pair, e.g. ETHUSDT")
    parser.add_argument("--side", required=True, choices=["buy", "sell"], help="Trade side")
    parser.add_argument("--fixture", action="store_true", help="Use fixture mode instead of live market data")
    parser.add_argument("--output", default="results", help="Directory for CSV output")
    parser.add_argument(
        "--size",
        type=float,
        default=None,
        help="Optional single size override; if omitted, run the default size sweep",
    )
    return parser


def _timing_output_path(output_path):
    output_path = Path(output_path)
    return output_path.with_name(f"{output_path.stem}_timing{output_path.suffix}")


def _fmt_float(value):
    if isinstance(value, float):
        return f"{value:.10f}".rstrip("0").rstrip(".")
    return value


def _comparison_rows(runid: str, comparison):
    rows = []
    for result in comparison.results:
        rows.append(
            {
                "runid": runid,
                "symbol": comparison.symbol,
                "side": comparison.side,
                "size": _fmt_float(comparison.size),
                "strategy": result.strategyname,
                "nchunks": result.nchunks,
                "cexallocation": _fmt_float(result.cexallocation),
                "dexallocation": _fmt_float(result.dexallocation),
                "totalcost": _fmt_float(result.totalcost),
                "costperunit": _fmt_float(result.costperunit),
                "vsnaivesavingspct": _fmt_float(savingspct(result, comparison)),
                "priceimpactavg": _fmt_float(result.priceimpactavg),
                "splitratio": _fmt_float(result.splitratio),
                "partialfill": result.partialfill,
                "snapshotts": comparison.snapshotts,
            }
        )
    return rows


def _write_csv(output_path: Path, rows, fieldnames) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_benchmark_baseline(path, summary, *, symbol, side, size, strategy, iterations):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "symbol": symbol,
        "side": side,
        "size": size,
        "strategy": strategy,
        "iterations": iterations,
        "n_samples": summary.n_samples,
        "p50_ms": summary.p50_ms,
        "p95_ms": summary.p95_ms,
        "p99_ms": summary.p99_ms,
        "min_ms": summary.min_ms,
        "max_ms": summary.max_ms,
        "mean_ms": summary.mean_ms,
        "breach_count": summary.breach_count,
        "breach_pct": summary.breach_pct,
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def _size_token(size: float) -> str:
    value = float(size)
    if value.is_integer():
        return str(int(value))
    return str(value).replace(".", "_")


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


def load_fixture_market_state(symbol: str, side: str, size: float):
    snapshot_path = FIXTURE_DIR / f"{symbol.lower()}_{side.lower()}_{_size_token(size)}_snapshot.json"
    pool_path = FIXTURE_DIR / f"{symbol.lower()}_{side.lower()}_{_size_token(size)}_pool.json"
    routes_path = FIXTURE_DIR / f"{symbol.lower()}_{side.lower()}_{_size_token(size)}_routes.json"

    for path in (snapshot_path, pool_path, routes_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing fixture file: {path}")

    with snapshot_path.open("r", encoding="utf-8") as fh:
        snapshot = json.load(fh)

    with pool_path.open("r", encoding="utf-8") as fh:
        pool = json.load(fh)

    with routes_path.open("r", encoding="utf-8") as fh:
        raw_routes = json.load(fh)

    def _to_namespace(value):
        if isinstance(value, dict):
            return SimpleNamespace(**{k: _to_namespace(v) for k, v in value.items()})
        if isinstance(value, list):
            return [_to_namespace(v) for v in value]
        return value

    class FixtureRouter:
        def __init__(self, routes):
            self.routes = [_to_namespace(route) for route in routes]
            self.is_fixture_router = True

        def find_best_route(self, snapshot, pool, size, side, enable_split=False):
            if not self.routes:
                raise AssertionError("No more fixture routes available.")
            return self.routes.pop(0)

    router = FixtureRouter(raw_routes)
    runid = f"fixture-{symbol.lower()}-{side.lower()}-{_size_token(size)}"

    return snapshot, pool, router, runid


def _build_live_router(snapshot, pool, side):
    raise NotImplementedError(
        "Live router construction is not implemented yet. "
        "Replace _build_live_router(...) with your real router factory/class."
    )


def _payload_snapshot_ts(payload):
    return (
        payload.get("snapshot_ts")
        or payload.get("timestamp")
        or payload.get("local_commit_ts_ms")
    )


def _commit_loaded_payload(
    freshness_tracker,
    *,
    symbol,
    source,
    payload,
):
    if not payload:
        raise RuntimeError(f"Missing live {source} payload for symbol={symbol}")

    committed = dict(payload)
    committed["source"] = committed.get("source", source)
    committed["snapshot_ts"] = _payload_snapshot_ts(committed)

    freshness_tracker.mark_updated(symbol, source)
    return committed


def load_live_market_state(symbol: str, side: str, freshness_tracker: FreshnessTracker):
    snapshot_payload_raw = redis_client.get(
        LIVE_BINANCE_REDIS_KEY.format(symbol=symbol)
    )
    pool_payload_raw = redis_client.get(
        LIVE_UNISWAP_REDIS_KEY.format(symbol=symbol)
    )

    if snapshot_payload_raw is None:
        raise RuntimeError(f"Missing live Binance payload for symbol={symbol}")
    if pool_payload_raw is None:
        raise RuntimeError(f"Missing live Uniswap payload for symbol={symbol}")

    snapshot_payload = json.loads(snapshot_payload_raw)
    pool_payload = json.loads(pool_payload_raw)

    snapshot = _commit_loaded_payload(
        freshness_tracker,
        symbol=symbol,
        source="binance",
        payload=snapshot_payload,
    )
    pool = _commit_loaded_payload(
        freshness_tracker,
        symbol=symbol,
        source="uniswap",
        payload=pool_payload,
    )

    router = _build_live_router(snapshot, pool, side)
    runid = f"live-{symbol.lower()}-{side.lower()}"

    return snapshot, pool, router, runid


def _selected_sizes(single_size: float | None):
    if single_size is not None:
        return [float(single_size)]
    return list(SIZE_GRID)


def _run_strategy(router, strategy, size):
    if strategy == "naive":
        return router.route_naive(size)
    if strategy == "chunked2":
        return router.route_chunked(size, chunks=2)
    if strategy == "chunked5":
        return router.route_chunked(size, chunks=5)
    if strategy == "chunked10":
        return router.route_chunked(size, chunks=10)
    if strategy == "split":
        split = getattr(router, "route_split", None)
        if callable(split):
            return split(size)
        execute = getattr(router, "execute_strategy", None)
        if callable(execute):
            return execute("split", size)
    raise ValueError(f"Unsupported strategy: {strategy}")


def _run_benchmark_only(
    *,
    args,
    latency_tracker,
    freshness_tracker,
):
    if latency_tracker is None:
        latency_tracker = LatencyTracker()
    
    if not args.fixture:
        raise ValueError("--benchmark-only currently requires --fixture")
    
    timing_rows = []

    benchmark_size = SIZE_GRID[0]
    benchmark_strategy = "comparison"

    for _ in range(BENCHMARK_ITERATIONS):

        snapshot, pool, router, runid = load_fixture_market_state(
            args.symbol,
            args.side,
            benchmark_size,
        )

        freshness_tracker.mark_updated(args.symbol, "binance")
        freshness_tracker.mark_updated(args.symbol, "uniswap")
        snapshot_ts = _snapshot_ts_from_state(snapshot, pool) or runid

        data_age_ms = freshness_tracker.effective_data_age_ms(
            args.symbol,
            HYBRID_SOURCES,
        )

        _, latency_record = latency_tracker.time_pipeline(
            run_id=runid,
            symbol=args.symbol,
            side=args.side,
            size=benchmark_size,
            strategy="comparison",
            data_age_ms=data_age_ms,
            snapshot_ts=snapshot_ts,
            parse_and_update=lambda: None,
            compute_route=lambda: comparestrategies(
                symbol=args.symbol,
                side=args.side,
                size=benchmark_size,
                snapshot=snapshot,
                pool=pool,
                router=router,
                runid=runid,
                snapshot_ts=snapshot_ts,
                latency_tracker=None
                ,
                freshness_tracker=freshness_tracker,
            ),
        )

        timing_rows.append(_timing_row(latency_record))

    summary = compute_summary(latency_tracker.buffer.to_list())

    print(
        "Latency summary: "
        f"n={summary.n_samples} "
        f"p50={summary.p50_ms:.3f}ms "
        f"p95={summary.p95_ms:.3f}ms "
        f"p99={summary.p99_ms:.3f}ms "
        f"mean={summary.mean_ms:.3f}ms "
        f"breaches={summary.breach_count} "
        f"breach_pct={summary.breach_pct:.2f}%"
    )

    _write_benchmark_baseline(
        BENCHMARK_BASELINE_PATH,
        summary,
        symbol=args.symbol,
        side=args.side,
        size=benchmark_size,
        strategy=benchmark_strategy,
        iterations=BENCHMARK_ITERATIONS,
    )

    benchmark_timing_path = Path("results/benchmark_latency.csv")
    _write_csv(benchmark_timing_path, timing_rows, TIMING_CSV_COLUMNS)


def _coalesce_ts_value(*values):
    for value in values:
        if value is not None and value != "":
            return str(value)
    return None


def _snapshot_ts_from_state(snapshot, pool):
    binance_ts = _coalesce_ts_value(
        getattr(snapshot, "snapshot_ts", None),
        getattr(snapshot, "timestamp", None),
        getattr(snapshot, "ts", None),
        snapshot.get("snapshot_ts") if isinstance(snapshot, dict) else None,
        snapshot.get("timestamp") if isinstance(snapshot, dict) else None,
        snapshot.get("ts") if isinstance(snapshot, dict) else None,
    )

    uniswap_ts = _coalesce_ts_value(
        getattr(pool, "snapshot_ts", None),
        getattr(pool, "timestamp", None),
        getattr(pool, "block_timestamp", None),
        getattr(pool, "block_number", None),
        pool.get("snapshot_ts") if isinstance(pool, dict) else None,
        pool.get("timestamp") if isinstance(pool, dict) else None,
        pool.get("block_timestamp") if isinstance(pool, dict) else None,
        pool.get("block_number") if isinstance(pool, dict) else None,
    )

    parts = []
    if binance_ts is not None:
        parts.append(f"binance={binance_ts}")
    if uniswap_ts is not None:
        parts.append(f"uniswap={uniswap_ts}")

    return "|".join(parts) if parts else None


def _mark_loaded_source_freshness(freshness_tracker, symbol, snapshot, pool):
    if snapshot is not None:
        freshness_tracker.mark_updated(symbol, "binance")
    if pool is not None:
        freshness_tracker.mark_updated(symbol, "uniswap")


def _assert_fresh_enough(freshness_tracker, symbol):
    return freshness_tracker.assert_not_stale(
        symbol,
        sources=HYBRID_SOURCES,
    )


def main() -> int:
    parser = build_parser()
    parser.add_argument(
        "--benchmark-only",
        action="store_true",
        help="Run 1000 timed route computations against a fixed fixture snapshot and skip normal experiment CSV output.",
    )
    args = parser.parse_args()

    latency_tracker = LatencyTracker()
    freshness_tracker = FreshnessTracker()


    if args.benchmark_only:
        _run_benchmark_only(
            args=args,
            latency_tracker=latency_tracker,
            freshness_tracker=freshness_tracker,
        )
        return 0

    timing_rows = []

    rows = []
    for size in _selected_sizes(args.size):
        if args.fixture:
            snapshot, pool, router, runid = load_fixture_market_state(
                args.symbol,
                args.side,
                size,
            )
            _mark_loaded_source_freshness(
                freshness_tracker,
                args.symbol,
                snapshot,
                pool,
            )
        else:
            snapshot, pool, router, runid = load_live_market_state(
                args.symbol,
                args.side,
                freshness_tracker,
            )
        
        snapshot_ts = _snapshot_ts_from_state(snapshot, pool) or runid

        comparison, comparison_timing_rows = comparestrategies(
            symbol=args.symbol,
            side=args.side,
            size=size,
            snapshot=snapshot,
            pool=pool,
            router=router,
            runid=runid,
            snapshot_ts=snapshot_ts,
            latency_tracker=latency_tracker,
            freshness_tracker=freshness_tracker,
        )
        rows.extend(_comparison_rows(runid, comparison))
        timing_rows.extend(comparison_timing_rows)

    output_path = Path(args.output)

    if output_path.suffix.lower() != ".csv":
        output_path = output_path / f"experiment_{args.symbol}_{args.side}.csv"

    _write_csv(output_path, rows, CSV_COLUMNS)
    _write_csv(_timing_output_path(output_path), timing_rows, TIMING_CSV_COLUMNS)
    summary = compute_summary(latency_tracker.buffer.to_list())
    print(
        "Latency summary: "
        f"n={summary.n_samples} "
        f"p50={summary.p50_ms:.3f}ms "
        f"p95={summary.p95_ms:.3f}ms "
        f"p99={summary.p99_ms:.3f}ms "
        f"mean={summary.mean_ms:.3f}ms "
        f"breaches={summary.breach_count} "
        f"breach_pct={summary.breach_pct:.2f}%"
    )

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())