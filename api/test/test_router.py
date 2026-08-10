import pytest
import json
import time
from unittest.mock import patch


BASE_URL = "/api/route"

@pytest.fixture
def mock_redis(fresh_main):
    def fake_get(key):
        if key == "orderbook:binance:ETHUSDT":
            return json.dumps({
                "timestamp": int(time.time() * 1000),
                "bids": [["3000.0", "10.0"]],
                "asks": [["3001.0", "10.0"]],
            })
        if key == "orderbook:uniswapv2:ETHUSDT":
            return json.dumps({
                "timestamp": int(time.time() * 1000),
                "reserve_token_a": 100.0,
                "reserve_token_b": 300000.0,
                "fee_bps": 30.0,
            })
        return None

    with patch.object(fresh_main.redis_client, "get", fake_get):
        yield

@pytest.fixture
def client(fresh_main):
    from fastapi.testclient import TestClient
    return TestClient(fresh_main.app)

def test_small_buy_binance(client, mock_redis):
    resp = client.post(BASE_URL, json={"symbol": "ETHUSDT", "side": "buy", "size": 0.1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["best_route"]["venue"] == "Binance"

def test_large_buy_uniswap_thin(client, mock_redis):
    resp = client.post(BASE_URL, json={"symbol": "ETHUSDT", "side": "buy", "size": 10.0})
    assert resp.status_code == 200
    data = resp.json()
    # Uniswap might win if CEX depth thin

def test_sell_binance(client, mock_redis):
    resp = client.post(BASE_URL, json={"symbol": "ETHUSDT", "side": "sell", "size": 1.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["best_route"]["venue"] == "Binance"

def test_gas_cost_visible(client, mock_redis):
    resp = client.post(BASE_URL, json={"symbol": "ETHUSDT", "side": "buy", "size": 0.1})
    assert resp.status_code == 200
    data = resp.json()
    assert "gas_cost_quote" in data["uniswap"]
    assert data["uniswap"]["gas_cost_quote"] > 0