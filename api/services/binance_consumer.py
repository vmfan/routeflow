import json
import os
import time

import redis
import requests

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
BINANCE_REST_BASE = os.getenv("BINANCE_REST_BASE", "https://api.binance.com")
BINANCE_WS_BASE = os.getenv("BINANCE_WS_BASE", "wss://stream.binance.com:9443")
SYMBOL = os.getenv("RF_SYMBOL", "ETHUSDT").upper()
DEPTH_LIMIT = int(os.getenv("BINANCE_DEPTH_LIMIT", "200"))
# Resync if either side of the local book falls below this many levels.
MIN_BOOK_LEVELS = int(os.getenv("BINANCE_MIN_BOOK_LEVELS", str(DEPTH_LIMIT // 2)))
WS_PING_INTERVAL_SECONDS = int(os.getenv("BINANCE_WS_PING_INTERVAL_SECONDS", "20"))
WS_PING_TIMEOUT_SECONDS = int(os.getenv("BINANCE_WS_PING_TIMEOUT_SECONDS", "10"))
RECONNECT_INITIAL_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0
LOG_EVERY_N_EVENTS = 100
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

OK = "ok"
STALE = "stale"
GAP = "gap"


class LocalOrderBook:
    """Order book rebuilt from a REST snapshot plus Binance diff-depth events.

    Follows Binance's documented procedure: drop events with u <= lastUpdateId, the
    first applied event must bracket lastUpdateId + 1, and every later event must
    start exactly at the previous event's u + 1. Anything else is a GAP and the caller
    must discard the book and resync from a fresh snapshot.
    """

    def __init__(self) -> None:
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.last_update_id: int | None = None
        self.last_applied_u: int | None = None
        self.last_event_time_ms: int | None = None
        self._first_event_applied = False

    def load_snapshot(self, snapshot: dict) -> None:
        self.bids = {}
        self.asks = {}
        self._apply_levels(self.bids, snapshot.get("bids", []))
        self._apply_levels(self.asks, snapshot.get("asks", []))
        self.last_update_id = int(snapshot["lastUpdateId"])
        self.last_applied_u = self.last_update_id
        self.last_event_time_ms = None
        self._first_event_applied = False

    @staticmethod
    def _apply_levels(side: dict[float, float], levels: list) -> None:
        for level in levels:
            if len(level) < 2:
                continue
            price = float(level[0])
            volume = float(level[1])
            if volume == 0:
                side.pop(price, None)
            else:
                side[price] = volume

    def apply_event(self, event: dict) -> str:
        if self.last_update_id is None:
            return GAP

        first_id = int(event["U"])
        final_id = int(event["u"])

        if not self._first_event_applied:
            if final_id <= self.last_update_id:
                return STALE
            if first_id > self.last_update_id + 1:
                return GAP
        elif first_id != self.last_applied_u + 1:
            return GAP

        self._apply_levels(self.bids, event.get("b", []))
        self._apply_levels(self.asks, event.get("a", []))
        self.last_applied_u = final_id
        event_time = event.get("E")
        self.last_event_time_ms = int(event_time) if event_time is not None else None
        self._first_event_applied = True
        return OK

    def is_thin(self, min_levels: int) -> bool:
        # Snapshots are truncated at DEPTH_LIMIT, so the book can only shrink as the
        # top levels are consumed. Resync before it gets too shallow to route against.
        return len(self.bids) < min_levels or len(self.asks) < min_levels

    def to_depth(self, limit: int) -> dict:
        bids = sorted(self.bids.items(), key=lambda level: level[0], reverse=True)[:limit]
        asks = sorted(self.asks.items(), key=lambda level: level[0])[:limit]
        return {
            "lastUpdateId": self.last_applied_u,
            "E": self.last_event_time_ms,
            "bids": [[price, volume] for price, volume in bids],
            "asks": [[price, volume] for price, volume in asks],
        }


class DepthStreamer:
    """WebSocketApp callbacks for one connection. Any failure closes the socket and
    the outer loop reconnects with a fresh snapshot."""

    def __init__(self, symbol: str, depth_limit: int, min_levels: int) -> None:
        self.symbol = symbol
        self.depth_limit = depth_limit
        self.min_levels = min_levels
        self.book = LocalOrderBook()
        self.events_applied = 0

    def on_open(self, ws) -> None:
        # The socket is already open (events are queuing) before the snapshot is
        # fetched, so no event after the snapshot can be missed. Events at or before
        # the snapshot's lastUpdateId are dropped by apply_event.
        try:
            self.book.load_snapshot(fetch_binance_depth(self.symbol))
            # Don't demand more depth than this symbol's snapshot actually had, or a
            # shallow book would resync forever.
            self.min_levels = max(
                1,
                min(self.min_levels, len(self.book.bids) // 2, len(self.book.asks) // 2),
            )
            print(f"Binance stream open for {self.symbol}; loaded snapshot lastUpdateId={self.book.last_update_id}")
        except Exception as exc:
            print(f"Binance snapshot error: {exc}")
            ws.close()

    def on_message(self, ws, message: str) -> None:
        try:
            event = json.loads(message)
            if event.get("e") != "depthUpdate":
                return

            status = self.book.apply_event(event)
            if status == STALE:
                return
            if status == GAP:
                print(f"Binance depth sequence gap for {self.symbol}; resyncing")
                ws.close()
                return
            if self.book.is_thin(self.min_levels):
                print(f"Binance book for {self.symbol} below {self.min_levels} levels per side; resyncing")
                ws.close()
                return

            self.events_applied += 1
            payload = normalize_depth_payload(self.symbol, self.book.to_depth(self.depth_limit))
            write_depth_to_redis(self.symbol, payload)
            on_depth_committed(self.symbol, payload)

            if self.events_applied == 1 or self.events_applied % LOG_EVERY_N_EVENTS == 0:
                print(
                    f"Wrote Binance depth for {self.symbol} with {len(payload['bids'])} bids, "
                    f"{len(payload['asks'])} asks (events={self.events_applied})"
                )
        except Exception as exc:
            print(f"Binance stream error: {exc}")
            ws.close()

    def on_error(self, ws, error) -> None:
        print(f"Binance websocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg) -> None:
        print(f"Binance websocket closed: code={close_status_code} msg={close_msg}")


def stream_url(symbol: str) -> str:
    return f"{BINANCE_WS_BASE.rstrip('/')}/ws/{symbol.lower()}@depth@100ms"


def run_stream_once(symbol: str = SYMBOL) -> int:
    """Run one connection until it closes. Returns the number of events applied."""
    import websocket  # websocket-client

    streamer = DepthStreamer(symbol, DEPTH_LIMIT, MIN_BOOK_LEVELS)
    app = websocket.WebSocketApp(
        stream_url(symbol),
        on_open=streamer.on_open,
        on_message=streamer.on_message,
        on_error=streamer.on_error,
        on_close=streamer.on_close,
    )
    # Client-side pings detect a half-open connection; Binance's own server pings are
    # answered automatically.
    app.run_forever(ping_interval=WS_PING_INTERVAL_SECONDS, ping_timeout=WS_PING_TIMEOUT_SECONDS)
    return streamer.events_applied


def main():
    backoff = RECONNECT_INITIAL_SECONDS
    while True:
        try:
            applied = run_stream_once(SYMBOL)
        except Exception as e:
            print(f"Binance producer error: {e}")
            applied = 0

        # A connection that delivered data was healthy, so reconnect quickly; repeated
        # immediate failures back off up to the cap.
        backoff = RECONNECT_INITIAL_SECONDS if applied > 0 else min(backoff * 2, RECONNECT_MAX_SECONDS)
        print(f"Reconnecting Binance stream in {backoff:.1f}s")
        time.sleep(backoff)

if __name__ == "__main__":
    main()