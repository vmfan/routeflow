import os

MAX_BINANCE_ORDERBOOK_AGE_MS = int(os.getenv("MAX_BINANCE_ORDERBOOK_AGE_MS", "5000"))
MAX_UNISWAP_POOL_AGE_MS = int(os.getenv("MAX_UNISWAP_POOL_AGE_MS", "30000"))
# Uniswap staleness is measured against the chain's block timestamp, so the limit must
# cover the block interval (~12s, ~24s on a missed slot) plus poll and RPC latency.