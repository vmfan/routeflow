## Run locally

### Prerequisites

Before running the project locally, make sure you have:

- A Python virtual environment in `api/`
- CMake available for building the C++ engine
- Docker running locally for Redis
- A valid `ETH_RPC_URL` for `api/uniswap_pool_producer.py`

### Environment variables

This project requires an Ethereum RPC URL for the Uniswap pool producer.

Example:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/routeflow
REDIS_URL=redis://localhost:6379
REDIS_HOST=localhost
REDIS_PORT=6379
QDRANT_HOST=localhost

BINANCE_WS_BASE=wss://stream.binance.com:9443
BINANCE_REST_BASE=https://api.binance.com
ETH_RPC_URL=YOUR_ETH_RPC_URL

MAX_BINANCE_ORDERBOOK_AGE_MS=5000
MAX_UNISWAP_POOL_AGE_MS=30000

RF_SYMBOL=ETHUSDT
UNISWAP_V2_PAIR_ADDRESS=0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852
TOKEN_A_SYMBOL=WETH
TOKEN_B_SYMBOL=USDT
UNISWAP_V2_FEE_BPS=30
POLL_INTERVAL_SECONDS=2
UNISWAP_REDIS_TTL_SECONDS=60

PORT=8000
```

### 1. Activate the Python environment

```bash
cd api
source venv/bin/activate
```

### 2. Build the C++ engine

```bash
cd ../cpp-engine
rm -rf build && cmake --preset dev && cmake --build --preset dev-build
```

### 3. Start the market data producers

Open separate terminals and run both producers from `api/`.

Binance producer:

```bash
cd api
source venv/bin/activate
python services/binance_consumer.py
```

Uniswap producer:

```bash
cd api
source venv/bin/activate
python services/uniswap_pool_producer.py
```

### 4. Start the API server

From the repository root:

```bash
python -m api.main
```

### 5. Test the route endpoint

```bash
curl -X POST "http://127.0.0.1:8000/api/route" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETHUSDT",
    "side": "buy",
    "size": 10.0,
    "enable_split": true
  }'
```

### Notes

- `api/uniswap_pool_producer.py` depends on `ETH_RPC_URL`.
- The Binance producer streams `<symbol>@depth@100ms` over `BINANCE_WS_BASE`, rebuilding a local order book (up to `BINANCE_DEPTH_LIMIT`, default 200 levels) from a REST snapshot (`BINANCE_REST_BASE`). It resyncs automatically on a sequence gap, a thin book, or a reconnect.
- The Uniswap producer reads token metadata once, then polls `get_block("latest")` + `getReserves()` (2 RPC calls per poll). Staleness is measured against the block's timestamp, so `MAX_UNISWAP_POOL_AGE_MS` must cover the block interval (~12s, ~24s on a missed slot) plus the poll interval.
- `REDIS_TTL_SECONDS` (default 10) applies to Binance. Uniswap uses `UNISWAP_REDIS_TTL_SECONDS` (falls back to `REDIS_TTL_SECONDS`, then 60) and should stay above `MAX_UNISWAP_POOL_AGE_MS`.
- Redis runs locally through Docker in this setup.
- The Binance and Uniswap producers should be running before sending requests to the API.
