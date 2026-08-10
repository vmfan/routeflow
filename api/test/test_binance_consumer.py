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