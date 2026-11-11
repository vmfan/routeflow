import json
import os
import requests
import time
import logging

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal, Optional
from pydantic import BaseModel, Field

import sys
from pathlib import Path

CPP_ENGINE_BUILD = Path(__file__).resolve().parents[1] / "cpp-engine" / "build"
sys.path.insert(0, str(CPP_ENGINE_BUILD))

import routeflowengine


app = FastAPI(title="RouteFlow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True,
)

logger = logging.getLogger("routeflow.api")

from api.config import (
    MAX_BINANCE_ORDERBOOK_AGE_MS,
    MAX_UNISWAP_POOL_AGE_MS,
)


class StaleDataError(Exception):
    def __init__(
        self,
        symbol: str,
        source: str,
        snapshot_timestamp_ms: int,
        now_ms: int,
        max_age_ms: int,
    ):
        self.symbol = symbol
        self.source = source
        self.snapshot_timestamp_ms = snapshot_timestamp_ms
        self.now_ms = now_ms
        self.max_age_ms = max_age_ms
        self.age_ms = now_ms - snapshot_timestamp_ms
        super().__init__(
            f"Stale market data for {symbol} on {source}: "
            f"age_ms={self.age_ms}, max_age_ms={self.max_age_ms}"
        )


@app.exception_handler(StaleDataError)
async def stale_data_exception_handler(request: Request, exc: StaleDataError):
    logger.warning(
        "stale_data_rejected symbol=%s source=%s age_ms=%s max_age_ms=%s",
        exc.symbol,
        exc.source,
        exc.age_ms,
        exc.max_age_ms,
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Cached market data is stale.",
            "symbol": exc.symbol,
            "source": exc.source,
            "snapshot_timestamp_ms": exc.snapshot_timestamp_ms,
            "now_ms": exc.now_ms,
            "age_ms": exc.age_ms,
            "max_age_ms": exc.max_age_ms,
        },
    )


def _load_snapshot_json(redis_key: str, missing_detail: str, invalid_detail: str) -> dict:
    raw = redis_client.get(redis_key)

    if not raw:
        # A missing snapshot means its producer is down (the key expired) or has not
        # started, so market data is unavailable: 503, consistent with stale data.
        raise HTTPException(status_code=503, detail=missing_detail)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=invalid_detail) from exc


def _resolve_snapshot_timestamp_ms(data: dict) -> int | None:
    return (
        data.get("snapshot_ts_ms")
        or data.get("snapshot_ts")
        or data.get("timestamp")
        or data.get("local_commit_ts_ms")
    )


def _extract_timestamp_ms(data: dict, source: str, symbol: str) -> int:
    timestamp = _resolve_snapshot_timestamp_ms(data)

    if timestamp is None:
        raise HTTPException(
            status_code=500,
            detail=f"{source} snapshot for {symbol} is missing timestamp",
        )

    try:
        timestamp_ms = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{source} snapshot for {symbol} has an invalid timestamp",
        ) from exc

    if timestamp_ms <= 0:
        raise HTTPException(
            status_code=500,
            detail=f"{source} snapshot for {symbol} has a non-positive timestamp",
        )

    if timestamp_ms < 1_000_000_000_000:
        raise HTTPException(
            status_code=500,
            detail=f"{source} snapshot for {symbol} timestamp must be in unix milliseconds",
        )

    return timestamp_ms


class RouteRequest(BaseModel):
    symbol: str = Field(..., examples=["ETHUSDT"])
    side: str = Field(..., examples=["buy", "sell"])
    size: float = Field(..., gt=0)
    enable_split: bool = Field(default=False, examples=[False, True])


class RouteSummaryResponse(BaseModel):
    venue: Optional[str] = None
    input_amount: float
    expected_output: float
    execution_price: Optional[float] = None
    slippage_pct: Optional[float] = None
    total_cost: Optional[float] = None
    unit_cost: Optional[float] = None
    gross_proceeds: Optional[float] = None
    net_proceeds: Optional[float] = None
    effective_proceeds: Optional[float] = None
    cex_slippage_pct: Optional[float] = None
    dex_price_impact_pct: Optional[float] = None


class VenueBreakdownBase(BaseModel):
    venue: str
    input_amount: float
    output_amount: float
    execution_price: float
    slippage_pct: float


class BinanceBreakdownResponse(VenueBreakdownBase):
    best_bid: float
    best_ask: float
    raw_cost: Optional[float] = None
    net_cost: Optional[float] = None
    unit_cost: Optional[float] = None
    raw_proceeds: Optional[float] = None
    net_proceeds: Optional[float] = None
    effective_proceeds: Optional[float] = None


class UniswapBreakdownResponse(VenueBreakdownBase):
    mid_price: float
    price_impact_pct: float
    gas_cost_native: float
    gas_cost_quote: float
    gas_cost_per_unit: float
    raw_cost: Optional[float] = None
    net_cost: Optional[float] = None
    unit_cost: Optional[float] = None
    raw_proceeds: Optional[float] = None
    net_proceeds: Optional[float] = None
    effective_proceeds: Optional[float] = None


class SplitLegResponse(BaseModel):
    venue: str
    ratio: float
    input_amount: float
    is_used: bool
    breakdown: VenueBreakdownBase


class SplitResultResponse(BaseModel):
    is_valid: bool
    improves_over_single: bool
    total_input_amount: float
    total_output_amount: float
    execution_price: Optional[float] = None
    slippage_pct: Optional[float] = None
    total_cost: Optional[float] = None
    gross_proceeds: Optional[float] = None
    net_proceeds: Optional[float] = None
    unit_cost: Optional[float] = None
    effective_proceeds: Optional[float] = None
    binance_leg: Optional[SplitLegResponse] = None
    uniswap_leg: Optional[SplitLegResponse] = None


class RouteResponse(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    input_amount: float
    best_route: RouteSummaryResponse
    routing_mode: str
    split_evaluated: bool
    split_recommended: bool
    split: Optional[SplitResultResponse] = None
    binance_timestamp_ms: Optional[int] = None
    uniswap_timestamp_ms: Optional[int] = None
    now_ms: Optional[int] = None
    binance: BinanceBreakdownResponse
    uniswap: UniswapBreakdownResponse

@app.get("/health")
async def health():
    return {"status": "ok", "service": "routeflow-api"}


def _load_snapshot_json(redis_key: str, missing_detail: str, invalid_detail: str) -> dict:
    raw = redis_client.get(redis_key)

    if not raw:
        # A missing snapshot means its producer is down (the key expired) or has not
        # started, so market data is unavailable: 503, consistent with stale data.
        raise HTTPException(status_code=503, detail=missing_detail)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=invalid_detail) from exc


def get_snapshot_timestamps(symbol: str) -> tuple[int, int, int]:
    symbol = symbol.upper()

    binance_data = _load_snapshot_json(
        f"orderbook:binance:{symbol}",
        f"Binance order book not found in Redis for symbol {symbol}",
        f"Invalid Binance order book JSON for symbol {symbol}",
    )
    uniswap_data = _load_snapshot_json(
        f"orderbook:uniswapv2:{symbol}",
        f"Uniswap V2 pool data not found in Redis for symbol {symbol}",
        f"Invalid Uniswap V2 pool JSON for symbol {symbol}",
    )

    binance_timestamp_ms = _extract_timestamp_ms(binance_data, "Binance", symbol)
    uniswap_timestamp_ms = _extract_timestamp_ms(uniswap_data, "Uniswap V2", symbol)
    now_ms = int(time.time() * 1000)

    return binance_timestamp_ms, uniswap_timestamp_ms, now_ms


def is_stale(symbol: str) -> tuple[int, int, int]:
    symbol = symbol.upper()

    binance_timestamp_ms, uniswap_timestamp_ms, now_ms = get_snapshot_timestamps(symbol)

    if binance_timestamp_ms > now_ms:
        raise HTTPException(
            status_code=500,
            detail=f"Binance snapshot for {symbol} has a future timestamp",
        )

    if uniswap_timestamp_ms > now_ms:
        raise HTTPException(
            status_code=500,
            detail=f"Uniswap V2 snapshot for {symbol} has a future timestamp",
        )

    if (now_ms - binance_timestamp_ms) > MAX_BINANCE_ORDERBOOK_AGE_MS:
        raise StaleDataError(
            symbol=symbol,
            source="Binance",
            snapshot_timestamp_ms=binance_timestamp_ms,
            now_ms=now_ms,
            max_age_ms=MAX_BINANCE_ORDERBOOK_AGE_MS,
        )

    if (now_ms - uniswap_timestamp_ms) > MAX_UNISWAP_POOL_AGE_MS:
        raise StaleDataError(
            symbol=symbol,
            source="Uniswap V2",
            snapshot_timestamp_ms=uniswap_timestamp_ms,
            now_ms=now_ms,
            max_age_ms=MAX_UNISWAP_POOL_AGE_MS,
        )


def load_binance_orderbook(symbol: str) -> routeflowengine.OrderBook:
    redis_key = f"orderbook:binance:{symbol.upper()}"
    raw = redis_client.get(redis_key)

    if not raw:
        raise HTTPException(
            status_code=503,
            detail=f"Binance order book not found in Redis for symbol {symbol.upper()}",
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid Binance order book JSON for symbol {symbol.upper()}",
        ) from exc

    bids = data.get("bids")
    asks = data.get("asks")

    if not bids or not isinstance(bids, list):
        raise HTTPException(
            status_code=500,
            detail=f"Binance order book for {symbol.upper()} must contain a bids list",
        )

    if not asks or not isinstance(asks, list):
        raise HTTPException(
            status_code=500,
            detail=f"Binance order book for {symbol.upper()} must contain an asks list",
        )

    book = routeflowengine.OrderBook()
    book.symbol = symbol.upper()

    timestamp = _resolve_snapshot_timestamp_ms(data)
    if timestamp is not None:
        try:
            book.timestamp = int(timestamp)
        except (TypeError, ValueError):
            pass

    for level in bids:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue

        try:
            price = float(level[0])
            volume = float(level[1])
        except (TypeError, ValueError):
            continue

        book.update("bid", price, volume)

    for level in asks:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue

        try:
            price = float(level[0])
            volume = float(level[1])
        except (TypeError, ValueError):
            continue

        book.update("ask", price, volume)

    return book


def load_uniswap_pool(symbol: str) -> routeflowengine.UniswapV2Pool:
    redis_key = f"orderbook:uniswapv2:{symbol.upper()}"
    raw = redis_client.get(redis_key)

    if not raw:
        raise HTTPException(
            status_code=503,
            detail=f"Uniswap V2 pool data not found in Redis for symbol {symbol.upper()}",
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid Uniswap V2 pool JSON for symbol {symbol.upper()}",
        ) from exc

    reserve_a = data.get("reserve_token_a")
    reserve_b = data.get("reserve_token_b")

    if reserve_a is None:
        reserve_a = data.get("reserveeth") or data.get("reserve_in")
    if reserve_b is None:
        reserve_b = data.get("reserveusdt") or data.get("reserve_out")

    if reserve_a is None or reserve_b is None:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Uniswap V2 pool data for {symbol.upper()} must contain "
                "reserve_token_a/reserve_token_b or equivalent reserve fields"
            ),
        )

    pool = routeflowengine.UniswapV2Pool()

    try:
        pool.reserve_token_a = float(reserve_a)
        pool.reserve_token_b = float(reserve_b)
        pool.fee_bps = float(data.get("fee_bps", 30.0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid numeric Uniswap V2 pool data for {symbol.upper()}",
        ) from exc

    return pool

def fetch_live_gas_price_gwei() -> float:
    fallback_gwei = float(os.getenv("FALLBACK_GAS_PRICE_GWEI", "2.0"))
    rpc_url = os.getenv("ETHEREUM_RPC_URL")
    if not rpc_url:
        return fallback_gwei

    payload = {
        "jsonrpc": "2.0",
        "method": "eth_gasPrice",
        "params": [],
        "id": 1,
    }

    try:
        response = requests.post(rpc_url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        result_hex = data.get("result")
        if not result_hex:
            return fallback_gwei
        return int(result_hex, 16) / 1e9
    except Exception:
        return fallback_gwei

def serialize_best_route(result) -> RouteSummaryResponse:
    is_buy = result.side == routeflowengine.TradeSide.Buy
    is_split = getattr(result, "routing_mode", None) == routeflowengine.RoutingMode.SplitOptimized

    payload = {
        "venue": None if is_split else routeflowengine.venue_to_string(result.best_venue),
        "input_amount": result.input_amount,
        "expected_output": result.expected_output,
        "execution_price": None if result.execution_price == 0.0 else result.execution_price,
        "slippage_pct": None if result.slippage_pct == 0.0 else result.slippage_pct,
        "cex_slippage_pct": None if result.binance.slippage_pct == 0.0 else result.binance.slippage_pct,
        "dex_price_impact_pct": (
            None if result.uniswap.price_impact_pct == 0.0 else result.uniswap.price_impact_pct
        ),
    }

    if is_buy:
        payload.update({
            "total_cost": result.total_cost,
            "unit_cost": result.unit_cost,
        })
    else:
        payload.update({
            "gross_proceeds": result.gross_proceeds,
            "net_proceeds": result.net_proceeds,
            "effective_proceeds": result.effective_proceeds,
        })

    return RouteSummaryResponse(**payload)


def serialize_binance_breakdown(breakdown, side: str) -> BinanceBreakdownResponse:
    is_buy = side == "buy"

    payload = {
        "venue": routeflowengine.venue_to_string(breakdown.venue),
        "input_amount": round(breakdown.input_amount, 12),
        "output_amount": round(breakdown.output_amount, 12),
        "execution_price": round(breakdown.execution_price, 12),
        "slippage_pct": round(breakdown.slippage_pct, 12),
        "best_bid": round(breakdown.best_bid, 12),
        "best_ask": round(breakdown.best_ask, 12),
    }

    if is_buy:
        payload.update({
            "raw_cost": breakdown.raw_cost,
            "net_cost": breakdown.net_cost,
            "unit_cost": breakdown.unit_cost,
        })
    else:
        payload.update({
            "raw_proceeds": breakdown.raw_proceeds,
            "net_proceeds": breakdown.net_proceeds,
            "effective_proceeds": breakdown.effective_proceeds,
        })

    return BinanceBreakdownResponse(**payload)


def serialize_uniswap_breakdown(breakdown, side: str) -> UniswapBreakdownResponse:
    is_buy = side == "buy"

    payload = {
        "venue": routeflowengine.venue_to_string(breakdown.venue),
        "input_amount": round(breakdown.input_amount, 12),
        "output_amount": round(breakdown.output_amount, 12),
        "execution_price": round(breakdown.execution_price, 12),
        "slippage_pct": round(breakdown.slippage_pct, 12),
        "mid_price": round(breakdown.mid_price, 12),
        "price_impact_pct": round(breakdown.price_impact_pct, 12),
        "gas_cost_native": round(breakdown.gas_cost_native, 12),
        "gas_cost_quote": round(breakdown.gas_cost_quote, 12),
        "gas_cost_per_unit": round(breakdown.gas_cost_per_unit, 12),
    }

    if is_buy:
        payload.update({
            "raw_cost": breakdown.raw_cost,
            "net_cost": breakdown.net_cost,
            "unit_cost": breakdown.unit_cost,
        })
    else:
        payload.update({
            "raw_proceeds": breakdown.raw_proceeds,
            "net_proceeds": breakdown.net_proceeds,
            "effective_proceeds": breakdown.effective_proceeds,
        })

    return UniswapBreakdownResponse(**payload)


def serialize_split_leg(leg, side: str) -> SplitLegResponse:
    if leg.venue == routeflowengine.Venue.Binance:
        breakdown = serialize_binance_breakdown(leg.breakdown, side)
    elif leg.venue == routeflowengine.Venue.Uniswap:
        breakdown = serialize_uniswap_breakdown(leg.breakdown, side)
    else:
        # Fallback: minimal venue breakdown
        from routeflowengine import venue_to_string
        breakdown = VenueBreakdownBase(
            venue=venue_to_string(leg.venue),
            input_amount=leg.breakdown.input_amount,
            output_amount=leg.breakdown.output_amount,
            execution_price=leg.breakdown.execution_price,
            slippage_pct=leg.breakdown.slippage_pct,
        )

    return SplitLegResponse(
        venue=routeflowengine.venue_to_string(leg.venue),
        ratio=round(leg.ratio, 6),
        input_amount=round(leg.input_amount, 12),
        is_used=leg.is_used,
        breakdown=breakdown,
    )


def serialize_split_result(split, side: str) -> SplitResultResponse:
    payload = {
        "is_valid": split.is_valid,
        "improves_over_single": split.improves_over_single,
        "total_input_amount": split.total_input_amount,
        "total_output_amount": split.total_output_amount,
        "execution_price": None if split.execution_price == 0.0 else split.execution_price,
        "slippage_pct": None if split.slippage_pct == 0.0 else split.slippage_pct,
    }

    is_buy = side == "buy"

    if is_buy:
        payload["total_cost"] = split.total_cost
        payload["unit_cost"] = split.unit_cost
    else:
        payload["gross_proceeds"] = split.gross_proceeds
        payload["net_proceeds"] = split.net_proceeds
        payload["effective_proceeds"] = split.effective_proceeds

    binance_leg = None
    uniswap_leg = None

    if split.binance_leg.is_used:
        binance_leg = serialize_split_leg(split.binance_leg, side)
    if split.uniswap_leg.is_used:
        uniswap_leg = serialize_split_leg(split.uniswap_leg, side)

    payload["binance_leg"] = binance_leg
    payload["uniswap_leg"] = uniswap_leg

    return SplitResultResponse(**payload)

@app.post(
    "/api/route",
    response_model=RouteResponse,
    response_model_exclude_none=True,
)
async def get_route(request: RouteRequest):
    symbol = request.symbol.upper()
    side = request.side.lower()

    if side not in {"buy", "sell"}:
        raise HTTPException(
            status_code=400,
            detail="This route endpoint supports side='buy' or side='sell' only.",
        )
    
    is_stale(symbol)
    binance_timestamp_ms, uniswap_timestamp_ms, now_ms = get_snapshot_timestamps(symbol)

    binance_book = load_binance_orderbook(symbol)
    uniswap_pool = load_uniswap_pool(symbol)

    gas_price_gwei = fetch_live_gas_price_gwei()
    BINANCE_TAKER_FEE_BPS = float(os.getenv("BINANCE_TAKER_FEE_BPS", "10.0"))
    UNISWAP_V2_SWAP_GAS = float(os.getenv("UNISWAP_V2_SWAP_GAS", "110000.0"))

    router = routeflowengine.Router(
        BINANCE_TAKER_FEE_BPS,
        UNISWAP_V2_SWAP_GAS,
        gas_price_gwei,
    )

    
    try:
        result = router.find_best_route(
            binance_book,
            uniswap_pool,
            request.size,
            side,
            enable_split=request.enable_split,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Routing engine failed: {str(exc)}",
        ) from exc

    side_str = routeflowengine.trade_side_to_string(result.side)

    split_result = None
    if request.enable_split and result.split_evaluated:
        split_result = serialize_split_result(result.split, side_str)

    return RouteResponse(
        symbol=symbol,
        side=side_str,
        input_amount=result.input_amount,
        best_route=serialize_best_route(result),
        routing_mode=routeflowengine.routing_mode_to_string(result.routing_mode),
        split_evaluated=result.split_evaluated,
        split_recommended=result.split_recommended,
        split=split_result,
        binance_timestamp_ms=binance_timestamp_ms,
        uniswap_timestamp_ms=uniswap_timestamp_ms,
        now_ms=now_ms,   
        binance=serialize_binance_breakdown(result.binance, side_str),
        uniswap=serialize_uniswap_breakdown(result.uniswap, side_str),
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)