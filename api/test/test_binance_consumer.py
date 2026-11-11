from api.services import binance_consumer
from api.services.binance_consumer import _binance_snapshot_ts, normalize_depth_payload, on_depth_committed


def test_binance_snapshot_ts_prefers_exchange_fields():
    depth = {"E": 1234567890, "lastUpdateId": 999}

    assert _binance_snapshot_ts(depth) == 1234567890


def test_binance_snapshot_ts_falls_back_to_last_update_id():
    depth = {"lastUpdateId": 999}

    assert _binance_snapshot_ts(depth) == 999


def test_normalize_depth_payload_includes_stage6_fields():
    depth = {
        "lastUpdateId": 555,
        "bids": [["3000.1", "1.25"]],
        "asks": [["3001.2", "2.50"]],
    }

    payload = normalize_depth_payload("ETHUSDT", depth)

    assert payload["source"] == "binance"
    assert payload["symbol"] == "ETHUSDT"
    assert payload["snapshot_ts"] == 555
    assert "local_commit_ts_ms" in payload
    assert payload["bids"] == [[3000.1, 1.25]]
    assert payload["asks"] == [[3001.2, 2.5]]


def test_normalize_depth_payload_skips_short_levels():
    depth = {
        "bids": [["3000.1"]],
        "asks": [["3001.2", "2.50"]],
    }

    payload = normalize_depth_payload("ETHUSDT", depth)

    assert payload["bids"] == []
    assert payload["asks"] == [[3001.2, 2.5]]


def test_main_commit_hook_can_be_called_after_payload_write(monkeypatch):
    calls = []

    monkeypatch.setattr(
        binance_consumer,
        "on_depth_committed",
        lambda symbol, payload: calls.append((symbol, payload["source"])),
    )

    payload = {"source": "binance"}
    binance_consumer.on_depth_committed("ETHUSDT", payload)

    assert calls == [("ETHUSDT", "binance")]

# --- LocalOrderBook / DepthStreamer ---------------------------------------------

from api.services.binance_consumer import GAP, OK, STALE, DepthStreamer, LocalOrderBook, stream_url


def _snapshot(last_update_id=100):
    return {
        "lastUpdateId": last_update_id,
        "bids": [["100.0", "1.0"], ["99.0", "2.0"], ["98.0", "3.0"]],
        "asks": [["101.0", "1.0"], ["102.0", "2.0"], ["103.0", "3.0"]],
    }


def _event(first, final, bids=(), asks=(), event_time=1_700_000_000_000):
    return {"e": "depthUpdate", "E": event_time, "U": first, "u": final, "b": list(bids), "a": list(asks)}


def test_local_book_loads_snapshot_and_orders_levels():
    book = LocalOrderBook()
    book.load_snapshot(_snapshot())

    depth = book.to_depth(2)

    assert depth["bids"] == [[100.0, 1.0], [99.0, 2.0]]
    assert depth["asks"] == [[101.0, 1.0], [102.0, 2.0]]


def test_local_book_drops_events_at_or_before_snapshot():
    book = LocalOrderBook()
    book.load_snapshot(_snapshot(100))

    assert book.apply_event(_event(90, 100, bids=[["100.0", "9.0"]])) == STALE
    assert book.bids[100.0] == 1.0


def test_local_book_first_event_must_bracket_snapshot():
    book = LocalOrderBook()
    book.load_snapshot(_snapshot(100))

    assert book.apply_event(_event(102, 105)) == GAP

    book.load_snapshot(_snapshot(100))
    assert book.apply_event(_event(101, 105)) == OK
    assert book.last_applied_u == 105


def test_local_book_first_event_may_straddle_snapshot_id():
    book = LocalOrderBook()
    book.load_snapshot(_snapshot(100))

    assert book.apply_event(_event(95, 110, bids=[["100.0", "4.0"]])) == OK
    assert book.bids[100.0] == 4.0


def test_local_book_applies_updates_and_removes_zero_quantity_levels():
    book = LocalOrderBook()
    book.load_snapshot(_snapshot(100))

    status = book.apply_event(
        _event(101, 101, bids=[["100.0", "0"], ["97.5", "5.0"]], asks=[["101.0", "7.0"]])
    )

    assert status == OK
    assert 100.0 not in book.bids
    assert book.bids[97.5] == 5.0
    assert book.asks[101.0] == 7.0
    assert book.to_depth(10)["bids"][0] == [99.0, 2.0]


def test_local_book_detects_gap_between_events():
    book = LocalOrderBook()
    book.load_snapshot(_snapshot(100))

    assert book.apply_event(_event(101, 105)) == OK
    assert book.apply_event(_event(106, 110)) == OK
    assert book.apply_event(_event(112, 115)) == GAP


def test_local_book_without_snapshot_reports_gap():
    assert LocalOrderBook().apply_event(_event(1, 2)) == GAP


def test_local_book_to_depth_feeds_normalize_depth_payload():
    book = LocalOrderBook()
    book.load_snapshot(_snapshot(100))
    book.apply_event(_event(101, 105, event_time=1_700_000_123_000))

    payload = normalize_depth_payload("ETHUSDT", book.to_depth(200))

    assert payload["exchange_update_id"] == 105
    assert payload["source_event_ts_ms"] == 1_700_000_123_000
    assert payload["snapshot_ts"] == 1_700_000_123_000
    assert payload["bids"][0] == [100.0, 1.0]
    assert payload["asks"][0] == [101.0, 1.0]


def test_local_book_is_thin_when_a_side_runs_low():
    book = LocalOrderBook()
    book.load_snapshot(_snapshot())

    assert not book.is_thin(3)
    assert book.is_thin(4)


class _FakeWS:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _streamer(monkeypatch, snapshot=None):
    import json as _json

    writes = []
    monkeypatch.setattr(binance_consumer, "fetch_binance_depth", lambda symbol: snapshot or _snapshot(100))
    monkeypatch.setattr(binance_consumer, "write_depth_to_redis", lambda symbol, payload: writes.append(payload))
    streamer = DepthStreamer("ETHUSDT", depth_limit=200, min_levels=1)
    ws = _FakeWS()
    streamer.on_open(ws)
    return streamer, ws, writes, _json.dumps


def test_streamer_writes_each_applied_event_and_skips_stale(monkeypatch):
    streamer, ws, writes, dumps = _streamer(monkeypatch)

    streamer.on_message(ws, dumps(_event(90, 100)))
    streamer.on_message(ws, dumps(_event(101, 101, bids=[["100.0", "5.0"]])))
    streamer.on_message(ws, dumps(_event(102, 102, asks=[["101.0", "0"]])))

    assert len(writes) == 2
    assert streamer.events_applied == 2
    assert writes[0]["bids"][0] == [100.0, 5.0]
    assert writes[1]["asks"][0] == [102.0, 2.0]
    assert not ws.closed


def test_streamer_closes_socket_on_sequence_gap(monkeypatch):
    streamer, ws, writes, dumps = _streamer(monkeypatch)

    streamer.on_message(ws, dumps(_event(101, 101)))
    streamer.on_message(ws, dumps(_event(150, 160)))

    assert ws.closed
    assert len(writes) == 1


def test_streamer_closes_socket_when_snapshot_fetch_fails(monkeypatch):
    def boom(symbol):
        raise RuntimeError("rest down")

    monkeypatch.setattr(binance_consumer, "fetch_binance_depth", boom)
    streamer = DepthStreamer("ETHUSDT", depth_limit=200, min_levels=1)
    ws = _FakeWS()

    streamer.on_open(ws)

    assert ws.closed


def test_streamer_ignores_non_depth_messages(monkeypatch):
    streamer, ws, writes, dumps = _streamer(monkeypatch)

    streamer.on_message(ws, dumps({"result": None, "id": 1}))
    streamer.on_message(ws, "not json")

    assert writes == []


def test_stream_url_uses_lowercase_symbol_and_100ms_diff_depth():
    assert stream_url("ETHUSDT").endswith("/ws/ethusdt@depth@100ms")
