import time
from pathlib import Path
import sys

from api.instrumentation import (
    FRESHNESS_CRITICAL_MS,
    FreshnessTracker,
    LatencyTracker,
    StaleDataError,
    compute_summary,
)

from api.scripts.runexperiments import comparestrategies


class SimulatedWebSocket:
    def __init__(self):
        self._messages = []
        self._paused = False
        self._closed = False

    def send_message(self, message: dict):
        if self._closed:
            raise RuntimeError("WebSocket is closed")
        if self._paused:
            return
        self._messages.append(message)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def close(self):
        self._paused = True
        self._closed = True

    def messages(self) -> list[dict]:
        return self._messages.copy()

    def clear_messages(self):
        self._messages.clear()

    def reconnect(self):
        self._closed = False
        self._paused = False


def test_simulated_websocket_close_is_terminal():
    ws = SimulatedWebSocket()

    ws.send_message({"symbol": "ETHUSDT", "E": 1000})
    assert len(ws.messages()) == 1

    ws.close()

    try:
        ws.send_message({"symbol": "ETHUSDT", "E": 1001})
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert str(exc) == "WebSocket is closed"


def test_freshness_tracker_rejects_stale_hybrid_state():
    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)
    tracker.mark_updated("ETHUSDT", "uniswap", updated_ns=1_000_000_000)

    try:
        tracker.assert_not_stale(
            "ETHUSDT",
            sources=["binance", "uniswap"],
            max_age_ms=FRESHNESS_CRITICAL_MS,
            now_ns=1_000_000_000 + int((FRESHNESS_CRITICAL_MS + 1.0) * 1_000_000),
        )
        assert False, "Expected StaleDataError"
    except StaleDataError as exc:
        assert "Stale data for symbol=ETHUSDT" in str(exc)


def test_freshness_tracker_data_age_increases_monotonically():
    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)
    tracker.mark_updated("ETHUSDT", "uniswap", updated_ns=1_200_000_000)

    age_1 = tracker.effective_data_age_ms(
        "ETHUSDT",
        ["binance", "uniswap"],
        now_ns=1_500_000_000,
    )
    age_2 = tracker.effective_data_age_ms(
        "ETHUSDT",
        ["binance", "uniswap"],
        now_ns=1_800_000_000,
    )

    assert age_1 == 500.0
    assert age_2 == 800.0
    assert age_2 > age_1


def test_latency_tracker_can_store_large_burst_of_records():
    tracker = LatencyTracker()

    for i in range(500):
        record = tracker.start_record(
            run_id=f"run-{i}",
            symbol="ETHUSDT",
            side="buy",
            size=1.0,
            strategy="split",
        )
        record.cache_updated_ns = record.msg_received_ns + 1_000_000
        record.route_complete_ns = record.cache_updated_ns + 2_000_000
        tracker.store(record)

    records = tracker.buffer.to_list()

    assert len(records) == 500
    assert all(record.total_ms == 3.0 for record in records)


def test_latency_summary_for_burst_has_no_target_breaches():
    tracker = LatencyTracker()

    for i in range(500):
        record = tracker.start_record(
            run_id=f"run-{i}",
            symbol="ETHUSDT",
            side="buy",
            size=1.0,
            strategy="split",
        )
        record.cache_updated_ns = record.msg_received_ns + 2_000_000
        record.route_complete_ns = record.cache_updated_ns + 3_000_000
        tracker.store(record)

    summary = compute_summary(tracker.buffer.to_list())

    assert summary.n_samples == 500
    assert summary.p99_ms == 5.0
    assert summary.breach_count == 0
    assert summary.breach_pct == 0.0


def test_simulated_websocket_can_reconnect_within_1_second():
    ws = SimulatedWebSocket()

    ws.send_message({"symbol": "ETHUSDT", "E": 1000})
    assert len(ws.messages()) == 1

    ws.close()

    start = time.perf_counter()
    ws.reconnect()
    ws.send_message({"symbol": "ETHUSDT", "E": 1001})
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0
    assert len(ws.messages()) == 2

def test_simulated_websocket_handles_500_message_burst_without_drops():
    ws = SimulatedWebSocket()

    for i in range(500):
        ws.send_message({"symbol": "ETHUSDT", "E": i})

    messages = ws.messages()

    assert len(messages) == 500
    assert messages[0]["E"] == 0
    assert messages[-1]["E"] == 499


def test_500_message_burst_p99_stays_below_100ms():
    ws = SimulatedWebSocket()
    tracker = LatencyTracker()

    for i in range(500):
        ws.send_message({"symbol": "ETHUSDT", "E": i})
        record = tracker.start_record(
            run_id=f"run-{i}",
            symbol="ETHUSDT",
            side="buy",
            size=1.0,
            strategy="split",
        )
        record.cache_updated_ns = record.msg_received_ns + 2_000_000
        record.route_complete_ns = record.cache_updated_ns + 3_000_000
        tracker.store(record)

    assert len(ws.messages()) == 500

    summary = compute_summary(tracker.buffer.to_list())

    assert summary.n_samples == 500
    assert summary.p99_ms < 100.0
    assert summary.breach_count == 0


def test_comparestrategies_rejects_stale_snapshot_before_routing():
    class StubRouter:
        pass

    tracker = FreshnessTracker()
    tracker.mark_updated("ETHUSDT", "binance", updated_ns=1_000_000_000)
    tracker.mark_updated("ETHUSDT", "uniswap", updated_ns=1_000_000_000)

    try:
        comparestrategies(
            symbol="ETHUSDT",
            side="buy",
            size=1.0,
            snapshot={},
            pool={},
            router=StubRouter(),
            runid="run-1",
            snapshot_ts="ts-1",
            latency_tracker=None,
            freshness_tracker=tracker,
        )
        assert False, "Expected StaleDataError"
    except StaleDataError:
        pass