from dotenv import load_dotenv
load_dotenv()

import json
import os
import time
from decimal import Decimal

import redis
from web3 import Web3

UNISWAP_SOURCE = "uniswap"

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "30"))

RF_SYMBOL = os.getenv("RF_SYMBOL", "ETHUSDT").upper()

ETH_RPC_URL = os.getenv("ETH_RPC_URL", "").strip()

# Mainnet Uniswap V2 WETH/USDT pair
PAIR_ADDRESS = os.getenv(
    "UNISWAP_V2_PAIR_ADDRESS",
    "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852",
).strip()

# Normalize into your app's token_a / token_b convention
TOKEN_A_SYMBOL = os.getenv("TOKEN_A_SYMBOL", "WETH").upper()
TOKEN_B_SYMBOL = os.getenv("TOKEN_B_SYMBOL", "USDT").upper()

FEE_BPS = float(os.getenv("UNISWAP_V2_FEE_BPS", "30.0"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))

PAIR_ABI = [
    {
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"internalType": "uint112", "name": "reserve0", "type": "uint112"},
            {"internalType": "uint112", "name": "reserve1", "type": "uint112"},
            {"internalType": "uint32", "name": "blockTimestampLast", "type": "uint32"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def to_float_amount(raw_value: int, decimals: int) -> float:
    return float(Decimal(raw_value) / (Decimal(10) ** Decimal(decimals)))


def get_token_metadata(w3: Web3, token_address: str) -> dict:
    token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
    symbol = token.functions.symbol().call()
    decimals = token.functions.decimals().call()
    return {
        "address": Web3.to_checksum_address(token_address),
        "symbol": str(symbol).upper(),
        "decimals": int(decimals),
    }


def fetch_pool_state(w3: Web3, pair_address: str) -> dict:
    pair = w3.eth.contract(address=Web3.to_checksum_address(pair_address), abi=PAIR_ABI)

    token0_address = pair.functions.token0().call()
    token1_address = pair.functions.token1().call()
    reserve0_raw, reserve1_raw, block_timestamp_last = pair.functions.getReserves().call()

    token0 = get_token_metadata(w3, token0_address)
    token1 = get_token_metadata(w3, token1_address)

    reserve0 = to_float_amount(reserve0_raw, token0["decimals"])
    reserve1 = to_float_amount(reserve1_raw, token1["decimals"])

    return {
        "pair_address": Web3.to_checksum_address(pair_address),
        "token0": token0,
        "token1": token1,
        "reserve0_raw": int(reserve0_raw),
        "reserve1_raw": int(reserve1_raw),
        "reserve0": reserve0,
        "reserve1": reserve1,
        "block_timestamp_last": int(block_timestamp_last),
    }


def _uniswap_snapshot_ts(payload: dict) -> int:
    ts = (
        payload.get("snapshot_ts")
        or payload.get("timestamp")
        or payload.get("block_timestamp_last")
        or payload.get("block_timestamp")
        or payload.get("blockTimestamp")
        or payload.get("updated_at")
    )

    if ts is None:
        raise ValueError("Uniswap snapshot is missing timestamp")

    try:
        return int(ts)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid Uniswap snapshot timestamp: {ts}") from exc

def normalize_for_routeflow(symbol: str, pool_state: dict) -> dict:
    token0 = pool_state["token0"]
    token1 = pool_state["token1"]

    token0_symbol = token0["symbol"]
    token1_symbol = token1["symbol"]

    reserve0 = pool_state["reserve0"]
    reserve1 = pool_state["reserve1"]

    if token0_symbol == TOKEN_A_SYMBOL and token1_symbol == TOKEN_B_SYMBOL:
        reserve_token_a = reserve0
        reserve_token_b = reserve1
    elif token0_symbol == TOKEN_B_SYMBOL and token1_symbol == TOKEN_A_SYMBOL:
        reserve_token_a = reserve1
        reserve_token_b = reserve0
    else:
        raise RuntimeError(
            "Pair tokens do not match configured TOKEN_A_SYMBOL/TOKEN_B_SYMBOL: "
            f"token0={token0_symbol}, token1={token1_symbol}, "
            f"expected {TOKEN_A_SYMBOL}/{TOKEN_B_SYMBOL}"
        )

    implied_price = reserve_token_b / reserve_token_a if reserve_token_a > 0 else None

    commit_ts_ms = int(time.time() * 1000)

    return {
        "source": UNISWAP_SOURCE,
        "symbol": symbol,
        "snapshot_ts": _uniswap_snapshot_ts(pool_state),
        "snapshot_ts_ms": commit_ts_ms,
        "source_event_ts_ms": _uniswap_source_event_ts_ms(pool_state),
        "local_commit_ts_ms": commit_ts_ms,
        "pair_address": pool_state["pair_address"],
        "reserve_token_a": reserve_token_a,
        "reserve_token_b": reserve_token_b,
        "fee_bps": FEE_BPS,
        "token0": pool_state["token0"],
        "token1": pool_state["token1"],
        "reserve0": pool_state["reserve0"],
        "reserve1": pool_state["reserve1"],
        "block_timestamp_last": pool_state["block_timestamp_last"],
        "implied_price_token_a_in_token_b": implied_price,
    }


def write_pool_to_redis(redis_client: redis.Redis, symbol: str, payload: dict) -> None:
    redis_key = f"orderbook:uniswapv2:{symbol}"
    redis_client.set(redis_key, json.dumps(payload), ex=REDIS_TTL_SECONDS)


def _uniswap_source_event_ts_ms(pool_state: dict) -> int | None:
    value = pool_state.get("block_timestamp_last")
    if value is None:
        return None
    return int(value) * 1000


def on_pool_committed(symbol: str, payload: dict) -> None:
    return None


def main() -> None:
    if not ETH_RPC_URL:
        raise RuntimeError("ETH_RPC_URL is required.")

    w3 = Web3(Web3.HTTPProvider(ETH_RPC_URL))
    if not w3.is_connected():
        raise RuntimeError("Failed to connect to Ethereum RPC.")

    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
    )

    while True:
        try:
            raw_pool_state = fetch_pool_state(w3, PAIR_ADDRESS)
            payload = normalize_for_routeflow(RF_SYMBOL, raw_pool_state)
            write_pool_to_redis(redis_client, RF_SYMBOL, payload)
            on_pool_committed(RF_SYMBOL, payload)

            print(
                f"Wrote {RF_SYMBOL} pool | source={payload['source']} | "
                f"snapshot_ts={payload['snapshot_ts_ms']} | "
                f"price≈{payload['implied_price_token_a_in_token_b']:.6f} "
                f"{TOKEN_B_SYMBOL}/{TOKEN_A_SYMBOL}"
            )
        except Exception as exc:
            print(f"Uniswap RPC producer error: {exc}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()