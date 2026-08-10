import json
import os
import time

import redis
import requests

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
BINANCE_REST_BASE = os.getenv("BINANCE_REST_BASE", "https://api.binance.com")
SYMBOL = os.getenv("RF_SYMBOL", "ETHUSDT").upper()
DEPTH_LIMIT = int(os.getenv("BINANCE_DEPTH_LIMIT", "200"))
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "10"))
BINANCE_SOURCE = "binance"

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def fetch_binance_depth(symbol: str) -> dict:
    url = f"{BINANCE_REST_BASE}/api/v3/depth"
    params = {"symbol": symbol, "limit": DEPTH_LIMIT}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()

def _binance_source_event_ts_ms(depth: dict) -> int | None:
    value = depth.get("E") or depth.get("T") or depth.get("timestamp") or depth.get("ts")
    return int(value) if value is not None else None

def _binance_snapshot_ts(payload: dict) -> int:
    ts = (
        payload.get("snapshot_ts")
        or payload.get("timestamp")
        or payload.get("T")
        or payload.get("E")
        or payload.get("lastUpdateId")
    )

    if ts is None:
        raise ValueError("Binance snapshot is missing timestamp")

    try:
        return int(ts)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid Binance snapshot timestamp: {ts}") from exc

def normalize_depth_payload(symbol: str, depth: dict) -> dict:
    bids = []
    asks = []
    
    for level in depth.get("bids", []):
        if len(level) < 2:
            continue
        price = float(level[0])
        volume = float(level[1])
        bids.append([price, volume])
    
    for level in depth.get("asks", []):
        if len(level) < 2:
            continue
        price = float(level[0])
        volume = float(level[1])
        asks.append([price, volume])

    commit_ts_ms = int(time.time() * 1000)

    return {
        "source": BINANCE_SOURCE,
        "symbol": symbol,
        "snapshot_ts": (
            _binance_snapshot_ts(depth)
            if any(k in depth for k in ("snapshot_ts", "timestamp", "T", "E", "lastUpdateId"))
            else None
        ),
        "snapshot_ts_ms": commit_ts_ms,
        "source_event_ts_ms": _binance_source_event_ts_ms(depth),
        "exchange_update_id": depth.get("lastUpdateId"),
        "local_commit_ts_ms": commit_ts_ms,
        "bids": bids,
        "asks": asks,
    }

def write_depth_to_redis(symbol: str, payload: dict) -> None:
    redis_key = f"orderbook:binance:{symbol}"
    redis_client.set(redis_key, json.dumps(payload), ex=REDIS_TTL_SECONDS)

def on_depth_committed(symbol: str, payload: dict) -> None:
    return None

def main():
    while True:
        try:
            depth = fetch_binance_depth(SYMBOL)
            payload = normalize_depth_payload(SYMBOL, depth)
            write_depth_to_redis(SYMBOL, payload)
            on_depth_committed(SYMBOL, payload)
            print(f"Wrote Binance depth for {SYMBOL} with {len(payload['bids'])} bids, {len(payload['asks'])} asks")
        except Exception as e:
            print(f"Binance producer error: {e}")
        time.sleep(2)

if __name__ == "__main__":
    main()