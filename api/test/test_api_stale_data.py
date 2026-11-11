import time

import pytest
from fastapi.testclient import TestClient
from api.config import MAX_BINANCE_ORDERBOOK_AGE_MS, MAX_UNISWAP_POOL_AGE_MS


@pytest.fixture
def client(fresh_main):
    return TestClient(fresh_main.app, raise_server_exceptions=False)

def _valid_binance_snapshot(timestamp_ms: int) -> dict:
    return {
        "timestamp": timestamp_ms,
        "bids": [["3000.0", "5.0"]],
        "asks": [["3001.0", "5.0"]],
    }


def _valid_uniswap_snapshot(timestamp_ms: int) -> dict:
    return {
        "timestamp": timestamp_ms,
        "reserve_token_a": 100.0,
        "reserve_token_b": 300000.0,
        "fee_bps": 30.0,
    }

def _patch_redis(monkeypatch, fresh_main, *, binance_data, uniswap_data):
    def fake_get(key: str):
        if key.startswith("orderbook:binance:"):
            import json
            return json.dumps(binance_data) if binance_data is not None else None
        if key.startswith("orderbook:uniswapv2:"):
            import json
            return json.dumps(uniswap_data) if uniswap_data is not None else None
        return None

    monkeypatch.setattr(fresh_main.redis_client, "get", fake_get)

def test_route_succeeds_when_snapshots_are_fresh(monkeypatch, fresh_main, client):
    now_ms = int(time.time() * 1000)

    _patch_redis(
        monkeypatch,
        fresh_main,
        binance_data=_valid_binance_snapshot(now_ms),
        uniswap_data=_valid_uniswap_snapshot(now_ms),
    )

    response = client.post(
        "/api/route",
        json={
            "symbol": "ETHUSDT",
            "side": "buy",
            "size": 1.0,
            "enable_split": False,
        },
    )

    assert response.status_code != 503

def test_route_returns_503_when_binance_snapshot_is_stale(monkeypatch, fresh_main, client):
    now_ms = int(time.time() * 1000)
    stale_binance_ms = now_ms - (MAX_BINANCE_ORDERBOOK_AGE_MS + 1)

    _patch_redis(
        monkeypatch,
        fresh_main,
        binance_data=_valid_binance_snapshot(stale_binance_ms),
        uniswap_data=_valid_uniswap_snapshot(now_ms),
    )

    response = client.post(
        "/api/route",
        json={
            "symbol": "ETHUSDT",
            "side": "buy",
            "size": 1.0,
            "enable_split": False,
        },
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "Cached market data is stale."
    assert body["symbol"] == "ETHUSDT"
    assert body["source"] == "Binance"
    assert body["max_age_ms"] == MAX_BINANCE_ORDERBOOK_AGE_MS
    assert body["age_ms"] > MAX_BINANCE_ORDERBOOK_AGE_MS

def test_route_returns_503_when_uniswap_snapshot_is_stale(monkeypatch, fresh_main, client):
    now_ms = int(time.time() * 1000)
    stale_uniswap_ms = now_ms - (MAX_UNISWAP_POOL_AGE_MS + 1)

    _patch_redis(
        monkeypatch,
        fresh_main,
        binance_data=_valid_binance_snapshot(now_ms),
        uniswap_data=_valid_uniswap_snapshot(stale_uniswap_ms),
    )

    response = client.post(
        "/api/route",
        json={
            "symbol": "ETHUSDT",
            "side": "sell",
            "size": 1.0,
            "enable_split": True,
        },
    )

    assert response.status_code == 503
    body = response.json()
    assert body["detail"] == "Cached market data is stale."
    assert body["symbol"] == "ETHUSDT"
    assert body["source"] == "Uniswap V2"
    assert body["max_age_ms"] == MAX_UNISWAP_POOL_AGE_MS
    assert body["age_ms"] > MAX_UNISWAP_POOL_AGE_MS

def test_route_returns_500_when_binance_timestamp_is_missing(monkeypatch, fresh_main, client):
    now_ms = int(time.time() * 1000)
    bad_binance = {
        "bids": [["3000.0", "5.0"]],
        "asks": [["3001.0", "5.0"]],
    }

    _patch_redis(
        monkeypatch,
        fresh_main,
        binance_data=bad_binance,
        uniswap_data=_valid_uniswap_snapshot(now_ms),
    )

    response = client.post(
        "/api/route",
        json={
            "symbol": "ETHUSDT",
            "side": "buy",
            "size": 1.0,
            "enable_split": False,
        },
    )

    assert response.status_code == 500
    assert "missing timestamp" in response.json()["detail"]

def test_route_returns_500_when_uniswap_timestamp_is_invalid(monkeypatch, fresh_main, client):
    now_ms = int(time.time() * 1000)
    bad_uniswap = _valid_uniswap_snapshot(now_ms)
    bad_uniswap["timestamp"] = "not-a-number"

    _patch_redis(
        monkeypatch,
        fresh_main,
        binance_data=_valid_binance_snapshot(now_ms),
        uniswap_data=bad_uniswap,
    )

    response = client.post(
        "/api/route",
        json={
            "symbol": "ETHUSDT",
            "side": "sell",
            "size": 1.0,
            "enable_split": False,
        },
    )

    assert response.status_code == 500
    assert "invalid timestamp" in response.json()["detail"]

def test_route_allows_snapshot_exactly_on_freshness_boundary(monkeypatch, fresh_main, client):
    fixed_now_ms = 1_700_000_000_000

    monkeypatch.setattr(time, "time", lambda: fixed_now_ms / 1000.0)

    binance_boundary_ms = fixed_now_ms - MAX_BINANCE_ORDERBOOK_AGE_MS
    uniswap_boundary_ms = fixed_now_ms - MAX_UNISWAP_POOL_AGE_MS

    _patch_redis(
        monkeypatch,
        fresh_main,
        binance_data=_valid_binance_snapshot(binance_boundary_ms),
        uniswap_data=_valid_uniswap_snapshot(uniswap_boundary_ms),
    )

    response = client.post(
        "/api/route",
        json={
            "symbol": "ETHUSDT",
            "side": "buy",
            "size": 1.0,
            "enable_split": False,
        },
    )

    assert response.status_code != 503

def test_route_accepts_uniswap_snapshot_within_block_time_budget(monkeypatch, fresh_main, client):
    now_ms = int(time.time() * 1000)

    _patch_redis(
        monkeypatch,
        fresh_main,
        binance_data=_valid_binance_snapshot(now_ms),
        uniswap_data=_valid_uniswap_snapshot(now_ms - 20_000),
    )

    response = client.post(
        "/api/route",
        json={"symbol": "ETHUSDT", "side": "buy", "size": 1.0, "enable_split": False},
    )

    assert response.status_code != 503


def test_route_returns_503_when_uniswap_snapshot_exceeds_limit(monkeypatch, fresh_main, client):
    now_ms = int(time.time() * 1000)

    _patch_redis(
        monkeypatch,
        fresh_main,
        binance_data=_valid_binance_snapshot(now_ms),
        uniswap_data=_valid_uniswap_snapshot(now_ms - (MAX_UNISWAP_POOL_AGE_MS + 1_000)),
    )

    response = client.post(
        "/api/route",
        json={"symbol": "ETHUSDT", "side": "buy", "size": 1.0, "enable_split": False},
    )

    assert response.status_code == 503
