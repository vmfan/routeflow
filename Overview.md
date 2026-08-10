# RouteFlow Overview

RouteFlow is a smart order router for cryptocurrency trading. Given an order (symbol, side, size), it finds the optimal execution path across a centralized exchange (Binance) and a decentralized exchange (Uniswap V2), including the option to split the order between both venues for better pricing.

---

## How It Works

1. **Market data producers** run continuously in the background, writing live snapshots to Redis:
   - `binance_consumer.py` — polls Binance REST every 2 seconds (top-200 order book depth, TTL 10s)
   - `uniswap_pool_producer.py` — calls `getReserves()` via Ethereum RPC every 10 seconds (TTL 30s)

2. **The API** (`POST /api/route`) receives an order request, loads fresh snapshots from Redis, and calls the C++ routing engine via pybind11.

3. **The C++ engine** computes:
   - A full quote for Binance (order book simulation)
   - A full quote for Uniswap V2 (AMM x·y=k formula, including price impact and gas cost)
   - 21 split ratios (0%…100% Binance in 5% steps), picking whichever minimizes unit cost (buy) or maximizes effective proceeds (sell)
   - The best single-venue route, compared against the best split — whichever wins is returned

4. **The response** includes per-venue breakdowns, the recommended route, and an optional split recommendation with ratio details.

---

## Architecture

```
┌─────────────────────────────┐
│  POST /api/route  (FastAPI) │
│  api/main.py                │
└──────────────┬──────────────┘
               │ pybind11
┌──────────────▼──────────────┐
│  C++ Routing Engine         │
│  cpp-engine/src/routing.cpp │
│  cpp-engine/src/orderbook   │
│  cpp-engine/src/uniswap_v2  │
└──────────────┬──────────────┘
               │
┌──────────────▼──────────────┐
│  Redis  (live snapshots)    │
└──────┬───────────┬──────────┘
       │           │
Binance Producer  Uniswap Producer
(REST, every 2s)  (ETH RPC, every 10s)
```

---

## Directory Structure

```
routeflow/
├── api/
│   ├── main.py                  # FastAPI app and /api/route endpoint
│   ├── models.py                # Pydantic request/response schemas
│   ├── strategies.py            # NaiveStrategy, ChunkedStrategy, HybridStrategy
│   ├── simulation.py            # Backtesting helpers (depletebook, evolvepool)
│   ├── instrumentation.py       # Latency tracker (100ms target) and freshness monitor
│   ├── explainability.py        # Human-readable routing decision summaries
│   ├── config.py                # Environment config loader
│   ├── formatter.py             # Output formatting utilities
│   ├── cli.py                   # CLI interface for manual testing
│   ├── services/
│   │   ├── binance_consumer.py  # Binance order book producer
│   │   └── uniswap_pool_producer.py  # Uniswap V2 pool state producer
│   ├── scripts/
│   │   └── runexperiments.py    # Benchmark runner
│   └── test/                    # pytest test suite
├── cpp-engine/
│   ├── src/
│   │   ├── routing.cpp/h        # Router class, find_best_route()
│   │   ├── orderbook.cpp/h      # Bid/ask maps, market order simulation
│   │   ├── uniswap_v2.cpp/h     # AMM math, gas cost normalization
│   │   ├── route_result.hpp     # Shared result structs
│   │   ├── json_bootstrap.cpp   # JSON parsing for market data
│   │   └── pythonbindings.cpp   # pybind11 module definition
│   └── CMakeLists.txt
├── results/                     # Benchmark CSVs
├── report/                      # Research documentation and figures
├── fixtures/                    # Test fixtures
└── README.md                    # Local setup and run instructions
```

---

## Economics Model

| Metric | Definition |
|--------|-----------|
| `unit_cost` | `net_cost / output_amount` — cost per unit received (buy side) |
| `effective_proceeds` | `net_proceeds / input_amount` — proceeds per unit sold (sell side) |
| `price_impact_pct` | Deviation from mid-price due to AMM slippage (Uniswap only) |
| `gas_cost_quote` | Ethereum gas cost converted to quote currency for cross-venue comparison |

Binance fees are applied as taker fee basis points. Uniswap fees (30 bps default) are embedded in the AMM formula. Gas is calculated as `gas_used × gas_price_gwei / 1e9` ETH, then converted to the quote token.

---

## Data Freshness

Stale market data triggers an HTTP 503 before any computation:

| Source | Max age |
|--------|---------|
| Binance order book | 5 seconds (`MAX_BINANCE_ORDERBOOK_AGE_MS`) |
| Uniswap pool state | 15 seconds (`MAX_UNISWAP_POOL_AGE_MS`) |

---

## Running Locally

See [README.md](README.md) for full setup instructions. The short version:

```bash
# 1. Build the C++ engine
cd cpp-engine && cmake --preset dev && cmake --build --preset dev-build

# 2. Start Redis (Docker)
docker run -p 6379:6379 redis

# 3. Start producers (separate terminals, from api/)
python binance_consumer.py
python uniswap_pool_producer.py

# 4. Start the API
python -m api.main

# 5. Send a test order
curl -X POST http://127.0.0.1:8000/api/route \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ETHUSDT","side":"buy","size":10.0,"enable_split":true}'
```

---

## Testing

```bash
# Python tests
cd api && pytest test/

# C++ tests
cd cpp-engine && cmake --build --preset dev-build && ctest
```

CI runs both suites via GitHub Actions (`.github/workflows/`).
