#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "orderbook.h"
#include "routing.h"
#include "uniswap_v2.h"
#include "route_result.hpp"

namespace py = pybind11;

PYBIND11_MODULE(routeflowengine, m) {
    m.doc() = "RouteFlow C++ execution routing engine";

    py::enum_<TradeSide>(m, "TradeSide")
        .value("Buy", TradeSide::Buy)
        .value("Sell", TradeSide::Sell);

    py::enum_<Venue>(m, "Venue")
        .value("Binance", Venue::Binance)
        .value("Uniswap", Venue::Uniswap)
        .value("Split", Venue::Split)
        .value("Unknown", Venue::Unknown);
     
    py::enum_<RoutingMode>(m, "RoutingMode")
        .value("SingleVenue", RoutingMode::SingleVenue)
        .value("SplitOptimized", RoutingMode::SplitOptimized);

    m.def("trade_side_to_string",
          [](TradeSide side) { return to_string(side); },
          py::arg("side"));

    m.def("venue_to_string",
          [](Venue venue) { return to_string(venue); },
          py::arg("venue"));

    m.def("routing_mode_to_string",
          [](RoutingMode mode) { return to_string(mode); },
          py::arg("mode"));

    py::class_<OrderBook>(m, "OrderBook")
        .def(py::init<>())
        .def_readwrite("symbol", &OrderBook::symbol)
        .def_readwrite("timestamp", &OrderBook::timestamp)
        .def("update", &OrderBook::update,
             py::arg("side"),
             py::arg("price"),
             py::arg("volume"))
        .def("best_bid_ask", &OrderBook::bestBidAsk)
        .def("simulate_market_buy", &OrderBook::simulateMarketBuy,
             py::arg("size"))
        .def("simulate_market_sell", &OrderBook::simulateMarketSell,
             py::arg("size"));

    py::class_<UniswapV2Pool>(m, "UniswapV2Pool")
        .def(py::init<>())
        .def_readwrite("reserve_token_a", &UniswapV2Pool::reserve_token_a)
        .def_readwrite("reserve_token_b", &UniswapV2Pool::reserve_token_b)
        .def_readwrite("fee_bps", &UniswapV2Pool::fee_bps)
        .def("get_amount_out_a_to_b", &UniswapV2Pool::get_amount_out_a_to_b,
             py::arg("amount_in"))
        .def("get_amount_out_b_to_a", &UniswapV2Pool::get_amount_out_b_to_a,
             py::arg("amount_in"))
        .def("get_amount_in_a_to_b", &UniswapV2Pool::get_amount_in_a_to_b,
             py::arg("amount_out"))
        .def("get_amount_in_b_to_a", &UniswapV2Pool::get_amount_in_b_to_a,
             py::arg("amount_out"))
        .def("mid_price_a_in_b", &UniswapV2Pool::mid_price_a_in_b)
        .def("mid_price_b_in_a", &UniswapV2Pool::mid_price_b_in_a)
        .def("estimate_swap_exact_in", &UniswapV2Pool::estimate_swap_exact_in,
             py::arg("amount_in"),
             py::arg("reserve_in"),
             py::arg("reserve_out"))
        .def("estimate_swap_exact_out", &UniswapV2Pool::estimate_swap_exact_out,
             py::arg("amount_out"),
             py::arg("reserve_in"),
             py::arg("reserve_out"))
        .def("estimate_swap_a_to_b", &UniswapV2Pool::estimate_swap_a_to_b,
             py::arg("amount_in"))
        .def("estimate_swap_b_to_a", &UniswapV2Pool::estimate_swap_b_to_a,
             py::arg("amount_in"))
        .def("estimate_buy_a_with_b", &UniswapV2Pool::estimate_buy_a_with_b,
             py::arg("amount_out_a"))
        .def("estimate_buy_b_with_a", &UniswapV2Pool::estimate_buy_b_with_a,
             py::arg("amount_out_b"))
        .def("compute_gas_adjusted_effective_cost",
             &UniswapV2Pool::compute_gas_adjusted_effective_cost,
             py::arg("execution_price"),
             py::arg("gas_cost_quote"),
             py::arg("amount_out"));

    py::class_<SwapResult>(m, "SwapResult")
        .def_readonly("amount_in", &SwapResult::amount_in)
        .def_readonly("amount_out", &SwapResult::amount_out)
        .def_readonly("execution_price", &SwapResult::execution_price)
        .def_readonly("price_impact_pct", &SwapResult::price_impact_pct)
        .def_readonly("unit_cost", &SwapResult::unit_cost)
        .def_readonly("gas_cost_native", &SwapResult::gas_cost_native)
        .def_readonly("gas_cost_quote", &SwapResult::gas_cost_quote);

    py::class_<VenueBreakdown>(m, "VenueBreakdown")
        .def_readonly("venue", &VenueBreakdown::venue)
        .def_readonly("input_amount", &VenueBreakdown::input_amount)
        .def_readonly("output_amount", &VenueBreakdown::output_amount)
        .def_readonly("execution_price", &VenueBreakdown::execution_price)
        .def_readonly("slippage_pct", &VenueBreakdown::slippage_pct)
        .def_readonly("raw_cost", &VenueBreakdown::raw_cost)
        .def_readonly("net_cost", &VenueBreakdown::net_cost)
        .def_readonly("unit_cost", &VenueBreakdown::unit_cost)
        .def_readonly("raw_proceeds", &VenueBreakdown::raw_proceeds)
        .def_readonly("net_proceeds", &VenueBreakdown::net_proceeds)
        .def_readonly("effective_proceeds", &VenueBreakdown::effective_proceeds)
        .def_readonly("best_bid", &VenueBreakdown::best_bid)
        .def_readonly("best_ask", &VenueBreakdown::best_ask)
        .def_readonly("mid_price", &VenueBreakdown::mid_price)
        .def_readonly("amount_in", &VenueBreakdown::amount_in)
        .def_readonly("amount_out", &VenueBreakdown::amount_out)
        .def_readonly("price_impact_pct", &VenueBreakdown::price_impact_pct)
        .def_readonly("gas_cost_native", &VenueBreakdown::gas_cost_native)
        .def_readonly("gas_cost_quote", &VenueBreakdown::gas_cost_quote)
        .def_readonly("gas_cost_per_unit", &VenueBreakdown::gas_cost_per_unit)
        .def_readonly("is_valid", &VenueBreakdown::is_valid);

    py::class_<SplitLeg>(m, "SplitLeg")
        .def_readonly("venue", &SplitLeg::venue)
        .def_readonly("ratio", &SplitLeg::ratio)
        .def_readonly("input_amount", &SplitLeg::input_amount)
        .def_readonly("breakdown", &SplitLeg::breakdown)
        .def_readonly("is_used", &SplitLeg::is_used);

    py::class_<SplitResult>(m, "SplitResult")
        .def_readonly("is_valid", &SplitResult::is_valid)
        .def_readonly("improves_over_single", &SplitResult::improves_over_single)
        .def_readonly("total_input_amount", &SplitResult::total_input_amount)
        .def_readonly("total_output_amount", &SplitResult::total_output_amount)
        .def_readonly("execution_price", &SplitResult::execution_price)
        .def_readonly("slippage_pct", &SplitResult::slippage_pct)
        .def_readonly("total_cost", &SplitResult::total_cost)
        .def_readonly("gross_proceeds", &SplitResult::gross_proceeds)
        .def_readonly("net_proceeds", &SplitResult::net_proceeds)
        .def_readonly("unit_cost", &SplitResult::unit_cost)
        .def_readonly("effective_proceeds", &SplitResult::effective_proceeds)
        .def_readonly("binance_leg", &SplitResult::binance_leg)
        .def_readonly("uniswap_leg", &SplitResult::uniswap_leg);

    py::class_<RouteResult>(m, "RouteResult")
        .def_readonly("side", &RouteResult::side)
        .def_readonly("best_venue", &RouteResult::best_venue)
        .def_readonly("input_amount", &RouteResult::input_amount)
        .def_readonly("expected_output", &RouteResult::expected_output)
        .def_readonly("execution_price", &RouteResult::execution_price)
        .def_readonly("slippage_pct", &RouteResult::slippage_pct)
        .def_readonly("total_cost", &RouteResult::total_cost)
        .def_readonly("gross_proceeds", &RouteResult::gross_proceeds)
        .def_readonly("net_proceeds", &RouteResult::net_proceeds)
        .def_readonly("unit_cost", &RouteResult::unit_cost)
        .def_readonly("effective_proceeds", &RouteResult::effective_proceeds)
        .def_readonly("chosen", &RouteResult::chosen)
        .def_readonly("binance", &RouteResult::binance)
        .def_readonly("uniswap", &RouteResult::uniswap)
        .def_readonly("routing_mode", &RouteResult::routing_mode)
        .def_readonly("split_evaluated", &RouteResult::split_evaluated)
        .def_readonly("split_recommended", &RouteResult::split_recommended)
        .def_readonly("split", &RouteResult::split);

    py::class_<Router>(m, "Router")
        .def(py::init<double, double, double>(),
             py::arg("binance_taker_fee_bps") = 10.0,
             py::arg("uniswap_swap_gas_used") = 110000.0,
             py::arg("gas_price_gwei") = 2.0)
        .def("find_best_route", &Router::find_best_route,
             py::arg("binance_book"),
             py::arg("uniswap_pool"),
             py::arg("size"),
             py::arg("side"),
             py::arg("enable_split") = false);
}