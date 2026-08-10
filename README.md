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
MAX_UNISWAP_POOL_AGE_MS=15000

RF_SYMBOL=ETHUSDT
UNISWAP_V2_PAIR_ADDRESS=0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852
TOKEN_A_SYMBOL=WETH
TOKEN_B_SYMBOL=USDT
UNISWAP_V2_FEE_BPS=30
POLL_INTERVAL_SECONDS=10
REDIS_TTL_SECONDS=30

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
python binance_consumer.py
```

Uniswap producer:

```bash
cd api
source venv/bin/activate
python uniswap_pool_producer.py
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
- Redis runs locally through Docker in this setup.
- The Binance and Uniswap producers should be running before sending requests to the API.
