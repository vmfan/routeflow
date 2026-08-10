import pytest

from api.instrumentation import (
    FRESHNESS_CRITICAL_MS,
    FRESHNESS_WARNING_MS,
    LATENCY_TARGET_MS,
    FreshnessTracker,
    LatencyBuffer,
    LatencyRecord,
    LatencyTracker,
    StaleDataError,
    compute_summary,
)


def test_latency_record_finalize_computes_expected_fields():
    record = LatencyRecord(
        run_id="run-1",
        symbol="ETHUSDT",
        msg_received_ns=1_000_000_000,
        cache_updated_ns=1_012_500_000,
        route_complete_ns=1_025_000_000,
    )

    record.finalize()

    assert record.parse_ms == 12.5
    assert record.compute_ms == 12.5
    assert record.total_ms == 25.0
    assert record.breached_target is False


def test_latency_record_marks_breach_when_total_exceeds_target():
    record = LatencyRecord(
        run_id="run-2",
        symbol="ETHUSDT",
        msg_received_ns=0,
        route_complete_ns=int((LATENCY_TARGET_MS + 1.0) * 1_000_000),
    )

    record.finalize()

    assert record.total_ms == LATENCY_TARGET_MS + 1.0
    assert record.breached_target is True


def test_latency_record_allows_partial_finalize_without_route_complete():
    record = LatencyRecord(
        run_id="run-3",
        symbol="ETHUSDT",
        msg_received_ns=2_000_000_000,
        cache_updated_ns=2_008_000_000,
    )

    record.finalize()

    assert record.parse_ms == 8.0
    assert record.compute_ms is None
    assert record.total_ms is None
    assert record.breached_target is False


def test_latency_buffer_wraps_at_maxlen():
    buffer = LatencyBuffer(maxlen=3)

    for i in range(5):
        buffer.append(
            LatencyRecord(
                run_id=f"run-{i}",
                symbol="ETHUSDT",
                msg_received_ns=i,
            )
        )

    records = buffer.to_list()

    assert len(records) == 3
    assert [record.run_id for record in records] == ["run-2", "run-3", "run-4"]


def test_compute_summary_returns_expected_statistics():
    records = [
        LatencyRecord(run_id="a", symbol="ETHUSDT", msg_received_ns=0, route_complete_ns=10_000_000),
        LatencyRecord(run_id="b", symbol="ETHUSDT", msg_received_ns=0, route_complete_ns=20_000_000),
        LatencyRecord(run_id="c", symbol="ETHUSDT", msg_received_ns=0, route_complete_ns=30_000_000),
        LatencyRecord(run_id="d", symbol="ETHUSDT", msg_received_ns=0, route_complete_ns=40_000_000),
        LatencyRecord(run_id="e", symbol="ETHUSDT", msg_received_ns=0, route_complete_ns=150_000_000),
    ]

    for record in records:
        record.finalize()

    summary = compute_summary(records)

    assert summary.n_samples == 5
    assert summary.min_ms == 10.0
    assert summary.max_ms == 150.0
    assert summary.mean_ms == pytest.approx(50.0, abs=1e-9)
    assert summary.breach_count == 1
    assert summary.breach_pct == 20.0
    assert summary.p50_ms == 30.0
    assert summary.p95_ms == pytest.approx(128.0, abs=1e-9)
    assert summary.p99_ms == pytest.approx(145.6, abs=1e-9)


def test_compute_summary_returns_zeroed_values_for_empty_input():
    summary = compute_summary([])

    assert summary.n_samples == 0
    assert summary.p50_ms == 0.0
    assert summary.p95_ms == 0.0
    assert summary.p99_ms == 0.0
    assert summary.min_ms == 0.0
    assert summary.max_ms == 0.0
    assert summary.mean_ms == 0.0
    assert summary.breach_count == 0
    assert summary.breach_pct == 0.0


def test_latency_tracker_times_pipeline_and_stores_record():
    tracker = LatencyTracker()

    state = {"parsed": False}

    def parse_and_update():
        state["parsed"] = True

    def compute_route():
        assert state["parsed"] is True
        return {"ok": True}

    result, record = tracker.time_pipeline(
        run_id="run-4",
        symbol="ETHUSDT",
        side="buy",
        size=5.0,
        strategy="split",
        parse_and_update=parse_and_update,
        compute_route=compute_route,
        data_age_ms=12.0,
        snapshot_ts="2026-05-10T23:00:00Z",
    )

    assert result == {"ok": True}
    assert len(tracker.buffer) == 1

    stored = tracker.buffer.to_list()[0]

    assert stored.run_id == "run-4"
    assert stored.symbol == "ETHUSDT"
    assert stored.side == "buy"
    assert stored.size == 5.0
    assert stored.strategy == "split"
    assert stored.data_age_ms == 12.0
    assert stored.snapshot_ts == "2026-05-10T23:00:00Z"
    assert stored.cache_updated_ns is not None
    assert stored.route_complete_ns is not None
    assert stored.parse_ms is not None
    assert stored.compute_ms is not None
    assert stored.total_ms is not None


def test_latency_tracker_stores_partial_record_on_exception():
    tracker = LatencyTracker()

    def parse_and_update():
        return None

    def compute_route():
        raise RuntimeError("route failed")

    try:
        tracker.time_pipeline(
            run_id="run-5",
            symbol="ETHUSDT",
            parse_and_update=parse_and_update,
            compute_route=compute_route,
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert str(exc) == "route failed"

    assert len(tracker.buffer) == 1

    stored = tracker.buffer.to_list()[0]
    assert stored.run_id == "run-5"
    assert stored.cache_updated_ns is not None
    assert stored.route_complete_ns is None
    assert stored.parse_ms is not None
    assert stored.compute_ms is None
    assert stored.total_ms is None


def test_latency_tracker_checkpoints_are_monotonic():
    tracker = LatencyTracker()

    def parse_and_update():
        return None

    def compute_route():
        return "done"

    _, record = tracker.time_pipeline(
        run_id="run-6",
        symbol="ETHUSDT",
        parse_and_update=parse_and_update,
        compute_route=compute_route,
    )

    assert record.msg_received_ns <= record.cache_updated_ns <= record.route_complete_ns


def test_freshness_tracker_returns_none_when_symbol_source_has_no_updates():
    tracker = FreshnessTracker()

    assert tracker.last_update_ns("ETHUSDT", "binance") is None
    assert tracker.data_age_ms("ETHUSDT", "binance") is None
    assert tracker.effective_data_age_ms("ETHUSDT", ["binance", "uniswap"]) is None
    assert tracker.status("ETHUSDT", ["binance", "uniswap"]) is None


def test_freshness_tracker_computes_per_source_data_age_ms():
    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)

    age_ms = tracker.data_age_ms("ETHUSDT", "binance", now_ns=1_250_000_000)

    assert age_ms == 250.0


def test_freshness_tracker_status_uses_oldest_required_source():
    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)
    tracker.mark_updated("ETHUSDT", "uniswap", updated_ns=2_000_000_000)

    assert tracker.status(
        "ETHUSDT",
        ["binance", "uniswap"],
        now_ns=2_500_000_000,
    ) == "warning"

    assert tracker.status(
        "ETHUSDT",
        ["binance", "uniswap"],
        now_ns=4_100_000_000,
    ) == "critical"


def test_freshness_tracker_raises_for_incomplete_required_sources():
    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)

    try:
        tracker.assert_not_stale("ETHUSDT", sources=["binance", "uniswap"])
        assert False, "Expected StaleDataError"
    except StaleDataError as exc:
        assert "No complete freshness state recorded" in str(exc)


def test_freshness_tracker_raises_when_oldest_required_source_is_stale():
    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)
    tracker.mark_updated("ETHUSDT", "uniswap", updated_ns=3_900_000_000)

    try:
        tracker.assert_not_stale(
            "ETHUSDT",
            sources=["binance", "uniswap"],
            max_age_ms=FRESHNESS_CRITICAL_MS,
            now_ns=4_100_000_000,
        )
        assert False, "Expected StaleDataError"
    except StaleDataError as exc:
        assert "Stale data for symbol=ETHUSDT" in str(exc)


def test_freshness_tracker_allows_when_all_required_sources_are_fresh():
    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)
    tracker.mark_updated("ETHUSDT", "uniswap", updated_ns=1_200_000_000)

    age_ms = tracker.assert_not_stale(
        "ETHUSDT",
        sources=["binance", "uniswap"],
        max_age_ms=FRESHNESS_CRITICAL_MS,
        now_ns=1_500_000_000,
    )

    assert age_ms == 500.0


def test_effective_data_age_ms_returns_oldest_required_source_age():
    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)
    tracker.mark_updated("ETHUSDT", "uniswap", updated_ns=1_300_000_000)

    age_ms = tracker.effective_data_age_ms(
        "ETHUSDT",
        ["binance", "uniswap"],
        now_ns=1_600_000_000,
    )

    assert age_ms == 600.0