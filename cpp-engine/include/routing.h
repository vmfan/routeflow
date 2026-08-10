#pragma once

#include <string>

#include "orderbook.h"
#include "uniswap_v2.h"
#include "route_result.hpp"

class Router {
public:
    explicit Router(double binance_taker_fee_bps = 10.0,
                    double uniswap_swap_gas_used = 110000.0,
                    double gas_price_gwei = 2.0)
            : binance_taker_fee_bps_(binance_taker_fee_bps),
              uniswap_swap_gas_used_(uniswap_swap_gas_used),
              gas_price_gwei_(gas_price_gwei) {}

    RouteResult find_best_route(const OrderBook& binance_book,
                                const UniswapV2Pool& uniswap_pool,
                                double base_amount,
                                const std::string& side,
                                bool enable_split = false) const;

private:
    double binance_taker_fee_bps_;
    double uniswap_swap_gas_used_;
    double gas_price_gwei_;

    double compute_binance_raw_total_cost(const OrderBook& binance_book,
                                          double base_amount_to_buy) const;

    double compute_binance_total_cost(const OrderBook& binance_book,
                                      double base_amount_to_buy) const;

    double compute_binance_effective_cost(const OrderBook& binance_book,
                                          double base_amount_to_buy) const;

    double compute_binance_raw_total_proceeds(const OrderBook& binance_book,
                                              double base_amount_to_sell) const;

    double compute_binance_net_proceeds(const OrderBook& binance_book,
                                        double base_amount_to_sell) const;

    double compute_binance_effective_proceeds(const OrderBook& binance_book,
                                              double base_amount_to_sell) const;

    double compute_pct_worse_than_reference(double execution_price,
                                            double reference_price) const;

    double compute_uniswap_gas_cost_native() const;
    double compute_uniswap_gas_cost_quote(double eth_usdt_reference) const;

    VenueBreakdown build_binance_buy_breakdown(const OrderBook& binance_book,
                                               double base_amount) const;

    VenueBreakdown build_binance_sell_breakdown(const OrderBook& binance_book,
                                                double base_amount) const;

    VenueBreakdown build_uniswap_buy_breakdown(const UniswapV2Pool& uniswap_pool,
                                               double base_amount) const;

    VenueBreakdown build_uniswap_sell_breakdown(const UniswapV2Pool& uniswap_pool,
                                                double base_amount) const;

    SplitLeg build_split_leg(Venue venue,
                             const VenueBreakdown& breakdown,
                             double ratio,
                             double input_amount) const;

    SplitResult evaluate_split_candidate(const OrderBook& binance_book,
                                         const UniswapV2Pool& uniswap_pool,
                                         TradeSide side,
                                         double total_base_amount,
                                         double binance_ratio) const;

    SplitResult find_best_split(const OrderBook& binance_book,
                                const UniswapV2Pool& uniswap_pool,
                                TradeSide side,
                                double total_base_amount) const;

    void apply_best_single_venue(RouteResult& result) const;

    void maybe_apply_split_result(RouteResult& result,
                                  const SplitResult& split_result) const;
};