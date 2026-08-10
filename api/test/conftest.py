import importlib
import sys
import types
from unittest import mock

import pytest

@pytest.fixture
def fake_routeflowengine_module():
    class FakeOrderBook:
        def __init__(self):
            self.symbol = ""
            self.timestamp = 0
            self.bids = []
            self.asks = []

        def update(self, side, price, volume):
            level = (float(price), float(volume))
            if side == "bid":
                self.bids.append(level)
            elif side == "ask":
                self.asks.append(level)

        def bestBidAsk(self):
            best_bid = max((p for p, _ in self.bids), default=0.0)
            best_ask = min((p for p, _ in self.asks), default=0.0)
            return best_bid, best_ask

    class FakeUniswapV2Pool:
        def __init__(self):
            self.reserve_token_a = 0.0
            self.reserve_token_b = 0.0
            self.fee_bps = 30.0

    class FakeVenueBreakdown:
        def __init__(self, **kwargs):
            self.venue = kwargs.get("venue")
            self.input_amount = kwargs.get("input_amount", 0.0)
            self.output_amount = kwargs.get("output_amount", 0.0)
            self.execution_price = kwargs.get("execution_price", 0.0)
            self.slippage_pct = kwargs.get("slippage_pct", 0.0)
            self.best_bid = kwargs.get("best_bid", 0.0)
            self.best_ask = kwargs.get("best_ask", 0.0)
            self.mid_price = kwargs.get("mid_price", 0.0)
            self.price_impact_pct = kwargs.get("price_impact_pct", 0.0)
            self.gas_cost_native = kwargs.get("gas_cost_native", 0.0)
            self.gas_cost_quote = kwargs.get("gas_cost_quote", 0.0)
            self.gas_cost_per_unit = kwargs.get("gas_cost_per_unit", 0.0)
            self.raw_cost = kwargs.get("raw_cost")
            self.net_cost = kwargs.get("net_cost")
            self.unit_cost = kwargs.get("unit_cost")
            self.raw_proceeds = kwargs.get("raw_proceeds")
            self.net_proceeds = kwargs.get("net_proceeds")
            self.effective_proceeds = kwargs.get("effective_proceeds")

    class FakeResult:
        pass

    class FakeRouter:
        def __init__(self, binance_taker_fee_bps=10.0, uniswap_swap_gas_used=110000.0, gas_price_gwei=2.0):
            self.binance_taker_fee_bps = binance_taker_fee_bps
            self.uniswap_swap_gas_used = uniswap_swap_gas_used
            self.gas_price_gwei = gas_price_gwei

        def find_best_route(self, binance_book, uniswap_pool, size, side, enable_split=False):
            result = FakeResult()
            result.side = "buy" if side == "buy" else "sell"
            result.routing_mode = "SingleVenue"
            result.split_evaluated = bool(enable_split)
            result.split_recommended = False
            result.split = None
            result.input_amount = size

            best_bid, best_ask = binance_book.bestBidAsk()
            gas_cost_quote = 0.66

            result.binance = FakeVenueBreakdown(
                venue="Binance",
                input_amount=size,
                output_amount=best_ask * size if side == "buy" else best_bid * size,
                execution_price=best_ask if side == "buy" else best_bid,
                slippage_pct=0.01,
                best_bid=best_bid,
                best_ask=best_ask,
                raw_cost=best_ask * size if side == "buy" else None,
                net_cost=(best_ask * size) * 1.001 if side == "buy" else None,
                unit_cost=best_ask * 1.001 if side == "buy" else None,
                raw_proceeds=best_bid * size if side == "sell" else None,
                net_proceeds=(best_bid * size) * 0.999 if side == "sell" else None,
                effective_proceeds=best_bid * 0.999 if side == "sell" else None,
            )

            uni_exec = (uniswap_pool.reserve_token_b / uniswap_pool.reserve_token_a) if uniswap_pool.reserve_token_a else 0.0
            result.uniswap = FakeVenueBreakdown(
                venue="Uniswap",
                input_amount=(uni_exec * size) if side == "buy" else size,
                output_amount=size if side == "buy" else (uni_exec * size),
                execution_price=uni_exec,
                slippage_pct=0.05,
                mid_price=uni_exec,
                price_impact_pct=0.05,
                gas_cost_native=0.00022,
                gas_cost_quote=gas_cost_quote,
                gas_cost_per_unit=gas_cost_quote / size if size else 0.0,
                raw_cost=(uni_exec * size) if side == "buy" else None,
                net_cost=((uni_exec * size) + gas_cost_quote) if side == "buy" else None,
                unit_cost=((uni_exec * size) + gas_cost_quote) / size if side == "buy" and size else None,
                raw_proceeds=(uni_exec * size) if side == "sell" else None,
                net_proceeds=((uni_exec * size) - gas_cost_quote) if side == "sell" else None,
                effective_proceeds=((uni_exec * size) - gas_cost_quote) / size if side == "sell" and size else None,
            )

            if side == "buy":
                if size <= 1.0:
                    result.best_venue = "Binance"
                    result.expected_output = size
                    result.execution_price = result.binance.execution_price
                    result.slippage_pct = result.binance.slippage_pct
                    result.total_cost = result.binance.net_cost
                    result.unit_cost = result.binance.unit_cost
                    result.gross_proceeds = None
                    result.net_proceeds = None
                    result.effective_proceeds = None
                else:
                    result.best_venue = "Uniswap"
                    result.expected_output = size
                    result.execution_price = result.uniswap.execution_price
                    result.slippage_pct = result.uniswap.slippage_pct
                    result.total_cost = result.uniswap.net_cost
                    result.unit_cost = result.uniswap.unit_cost
                    result.gross_proceeds = None
                    result.net_proceeds = None
                    result.effective_proceeds = None
            else:
                result.best_venue = "Binance"
                result.expected_output = result.binance.net_proceeds
                result.execution_price = result.binance.execution_price
                result.slippage_pct = result.binance.slippage_pct
                result.total_cost = None
                result.unit_cost = None
                result.gross_proceeds = result.binance.raw_proceeds
                result.net_proceeds = result.binance.net_proceeds
                result.effective_proceeds = result.binance.effective_proceeds

            return result

    return types.SimpleNamespace(
        TradeSide=types.SimpleNamespace(Buy="buy", Sell="sell"),
        RoutingMode=types.SimpleNamespace(SingleVenue="SingleVenue", SplitOptimized="SplitOptimized"),
        Venue=types.SimpleNamespace(Binance="Binance", Uniswap="Uniswap", Split="Split", Unknown="Unknown"),
        venue_to_string=lambda venue: str(venue),
        trade_side_to_string=lambda side: str(side),
        routing_mode_to_string=lambda mode: str(mode),
        OrderBook=FakeOrderBook,
        UniswapV2Pool=FakeUniswapV2Pool,
        Router=FakeRouter,
    )

@pytest.fixture
def fresh_main(fake_routeflowengine_module):
    with mock.patch.dict(sys.modules, {"routeflowengine": fake_routeflowengine_module}):
        sys.modules.pop("api.main", None)
        importlib.invalidate_caches()
        main = importlib.import_module("api.main")
        yield main
        sys.modules.pop("api.main", None)