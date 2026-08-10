#include "routing.h"

#include <stdexcept>
#include <string>
#include <limits>

double Router::compute_binance_raw_total_cost(const OrderBook& binance_book,
                                              double base_amount_to_buy) const {
    if (base_amount_to_buy <= 0.0) {
        throw std::invalid_argument("base_amount_to_buy must be greater than zero.");
    }

    const double raw_total_cost = binance_book.simulateMarketBuy(base_amount_to_buy);

    if (raw_total_cost < 0.0) {
        throw std::runtime_error("Binance order book cannot fill this buy trade size.");
    }

    return raw_total_cost;
}

double Router::compute_binance_total_cost(const OrderBook& binance_book,
                                          double base_amount_to_buy) const {
    const double raw_total_cost = compute_binance_raw_total_cost(binance_book, base_amount_to_buy);
    const double fee_rate = binance_taker_fee_bps_ / 10000.0;
    const double fee_amount = raw_total_cost * fee_rate;
    return raw_total_cost + fee_amount;
}

double Router::compute_binance_effective_cost(const OrderBook& binance_book,
                                              double base_amount_to_buy) const {
    const double total_cost = compute_binance_total_cost(binance_book, base_amount_to_buy);
    return total_cost / base_amount_to_buy;
}

double Router::compute_binance_raw_total_proceeds(const OrderBook& binance_book,
                                                  double base_amount_to_sell) const {
    if (base_amount_to_sell <= 0.0) {
        throw std::invalid_argument("base_amount_to_sell must be greater than zero.");
    }

    const double raw_total_proceeds = binance_book.simulateMarketSell(base_amount_to_sell);

    if (raw_total_proceeds < 0.0) {
        throw std::runtime_error("Binance order book cannot fill this sell trade size.");
    }

    return raw_total_proceeds;
}

double Router::compute_binance_net_proceeds(const OrderBook& binance_book,
                                            double base_amount_to_sell) const {
    const double raw_total_proceeds = compute_binance_raw_total_proceeds(binance_book, base_amount_to_sell);
    const double fee_rate = binance_taker_fee_bps_ / 10000.0;
    const double fee_amount = raw_total_proceeds * fee_rate;
    return raw_total_proceeds - fee_amount;
}

double Router::compute_binance_effective_proceeds(const OrderBook& binance_book,
                                                  double base_amount_to_sell) const {
    const double net_proceeds = compute_binance_net_proceeds(binance_book, base_amount_to_sell);
    return net_proceeds / base_amount_to_sell;
}

double Router::compute_pct_worse_than_reference(double execution_price,
                                                double reference_price) const {
    if (reference_price <= 0.0) {
        throw std::invalid_argument("reference_price must be greater than zero.");
    }

    const double pct = ((execution_price - reference_price) / reference_price) * 100.0;
    return pct < 0.0 ? 0.0 : pct;
}

double Router::compute_uniswap_gas_cost_native() const {
    if (uniswap_swap_gas_used_ < 0.0 || gas_price_gwei_ < 0.0) {
        throw std::invalid_argument("Uniswap gas inputs must be non-negative.");
    }

    const double gas_price_eth = gas_price_gwei_ * 1e-9;
    return uniswap_swap_gas_used_ * gas_price_eth;
}

double Router::compute_uniswap_gas_cost_quote(double eth_usdt_reference) const {
    if (eth_usdt_reference <= 0.0) {
        throw std::invalid_argument("eth_usdt_reference must be greater than zero.");
    }

    const double gas_cost_native = compute_uniswap_gas_cost_native();
    return gas_cost_native * eth_usdt_reference;
}

VenueBreakdown Router::build_binance_buy_breakdown(const OrderBook& binance_book,
                                                   double base_amount) const {
    VenueBreakdown v;
    v.venue = Venue::Binance;
    v.input_amount = base_amount;

    const auto best_bid_ask = binance_book.bestBidAsk();
    const double best_ask = best_bid_ask.second;

    if (best_ask <= 0.0) {
        throw std::runtime_error("Binance best ask is invalid.");
    }

    const double raw_cost = compute_binance_raw_total_cost(binance_book, base_amount);
    const double net_cost = compute_binance_total_cost(binance_book, base_amount);
    const double raw_execution_price = raw_cost / base_amount;
    const double effective_cost = net_cost / base_amount;
    const double slippage_pct = compute_pct_worse_than_reference(raw_execution_price, best_ask);

    v.output_amount = raw_cost;
    v.execution_price = raw_execution_price;
    v.slippage_pct = slippage_pct;

    v.raw_cost = raw_cost;
    v.net_cost = net_cost;
    v.unit_cost = effective_cost;

    v.best_ask = best_ask;
    v.best_bid = best_bid_ask.first;
    v.is_valid = true;

    return v;
}

VenueBreakdown Router::build_binance_sell_breakdown(const OrderBook& binance_book,
                                                    double base_amount) const {
    VenueBreakdown v;
    v.venue = Venue::Binance;
    v.input_amount = base_amount;

    const auto best_bid_ask = binance_book.bestBidAsk();
    const double best_bid = best_bid_ask.first;

    if (best_bid <= 0.0) {
        throw std::runtime_error("Binance best bid is invalid.");
    }

    const double raw_proceeds = compute_binance_raw_total_proceeds(binance_book, base_amount);
    const double net_proceeds = compute_binance_net_proceeds(binance_book, base_amount);
    const double raw_execution_price = raw_proceeds / base_amount;
    const double effective_proceeds = net_proceeds / base_amount;

    v.output_amount = raw_proceeds;
    v.execution_price = raw_execution_price;
    v.slippage_pct = compute_pct_worse_than_reference(best_bid, raw_execution_price);

    v.raw_proceeds = raw_proceeds;
    v.net_proceeds = net_proceeds;
    v.effective_proceeds = effective_proceeds;

    v.best_bid = best_bid;
    v.best_ask = best_bid_ask.second;
    v.is_valid = true;

    return v;
}

VenueBreakdown Router::build_uniswap_buy_breakdown(const UniswapV2Pool& uniswap_pool,
                                                   double base_amount) const {
    VenueBreakdown v;
    v.venue = Venue::Uniswap;
    v.input_amount = base_amount;

    const double mid_price = uniswap_pool.mid_price_a_in_b();
    if (mid_price <= 0.0) {
        throw std::runtime_error("Uniswap mid price is invalid.");
    }

    const SwapResult quote = uniswap_pool.estimate_buy_a_with_b(base_amount);
    if (quote.amount_in <= 0.0 || quote.amount_out <= 0.0) {
        throw std::runtime_error("Invalid Uniswap buy quote.");
    }

    const double gas_cost_native = compute_uniswap_gas_cost_native();
    const double gas_cost_quote = compute_uniswap_gas_cost_quote(mid_price);
    const double gas_cost_per_unit = gas_cost_quote / base_amount;
    const double effective_cost =
        uniswap_pool.compute_gas_adjusted_effective_cost(
            quote.execution_price,
            gas_cost_quote,
            base_amount
        );

    v.input_amount = base_amount;
    v.output_amount = quote.amount_in;
    v.execution_price = quote.execution_price;
    v.slippage_pct = quote.price_impact_pct;

    v.raw_cost = quote.amount_in;
    v.net_cost = quote.amount_in + gas_cost_quote;
    v.unit_cost = effective_cost;

    v.mid_price = mid_price;
    v.amount_in = quote.amount_in;
    v.amount_out = quote.amount_out;
    v.price_impact_pct = quote.price_impact_pct;

    v.gas_cost_native = gas_cost_native;
    v.gas_cost_quote = gas_cost_quote;
    v.gas_cost_per_unit = gas_cost_per_unit;
    v.is_valid = true;

    return v;
}

VenueBreakdown Router::build_uniswap_sell_breakdown(const UniswapV2Pool& uniswap_pool,
                                                    double base_amount) const {
    VenueBreakdown v;
    v.venue = Venue::Uniswap;
    v.input_amount = base_amount;

    const double mid_price = uniswap_pool.mid_price_a_in_b();
    if (mid_price <= 0.0) {
        throw std::runtime_error("Uniswap mid price is invalid.");
    }

    const SwapResult quote = uniswap_pool.estimate_swap_a_to_b(base_amount);
    if (quote.amount_in <= 0.0 || quote.amount_out <= 0.0) {
        throw std::runtime_error("Invalid Uniswap sell quote.");
    }

    const double gas_cost_native = compute_uniswap_gas_cost_native();
    const double gas_cost_quote = compute_uniswap_gas_cost_quote(mid_price);
    const double gas_cost_per_unit = gas_cost_quote / base_amount;

    const double sell_execution_price = quote.amount_out / quote.amount_in;
    const double net_proceeds = quote.amount_out - gas_cost_quote;
    const double effective_proceeds = net_proceeds / base_amount;

    v.input_amount = quote.amount_in;
    v.output_amount = quote.amount_out;
    v.execution_price = sell_execution_price;
    v.slippage_pct = compute_pct_worse_than_reference(mid_price, sell_execution_price);

    v.raw_proceeds = quote.amount_out;
    v.net_proceeds = net_proceeds;
    v.effective_proceeds = effective_proceeds;

    v.mid_price = mid_price;
    v.amount_in = quote.amount_in;
    v.amount_out = quote.amount_out;
    v.price_impact_pct = compute_pct_worse_than_reference(mid_price, sell_execution_price);

    v.gas_cost_native = gas_cost_native;
    v.gas_cost_quote = gas_cost_quote;
    v.gas_cost_per_unit = gas_cost_per_unit;
    v.is_valid = true;

    return v;
}

SplitLeg Router::build_split_leg(Venue venue,
                                 const VenueBreakdown& breakdown,
                                 double ratio,
                                 double input_amount) const {
    SplitLeg leg;
    leg.venue = venue;
    leg.ratio = ratio;
    leg.input_amount = input_amount;
    leg.breakdown = breakdown;
    leg.is_used = true;
    return leg;
}

SplitResult Router::evaluate_split_candidate(const OrderBook& binance_book,
                                             const UniswapV2Pool& uniswap_pool,
                                             TradeSide side,
                                             double total_base_amount,
                                             double binance_ratio) const {
    SplitResult result;
    result.is_valid = false;

    if (binance_ratio < 0.0 || binance_ratio > 1.0) {
        return result;
    }

    const double uniswap_ratio = 1.0 - binance_ratio;
    result.total_input_amount = total_base_amount;

    const double binance_base = binance_ratio * total_base_amount;
    const double uniswap_base = uniswap_ratio * total_base_amount;

    const bool is_buy = (side == TradeSide::Buy);

    if (binance_base > 1e-12) {
        VenueBreakdown binance_leg_breakdown;
        try {
            if (is_buy) {
                binance_leg_breakdown = build_binance_buy_breakdown(binance_book, binance_base);
            } else {
                binance_leg_breakdown = build_binance_sell_breakdown(binance_book, binance_base);
            }
        } catch (...) {
            return result;
        }

        if (!binance_leg_breakdown.is_valid) {
            return result;
        }

        result.binance_leg = build_split_leg(Venue::Binance, binance_leg_breakdown, binance_ratio, binance_base);
    } else {
        result.binance_leg.is_used = false;
        result.binance_leg.ratio = 0.0;
        result.binance_leg.input_amount = 0.0;
    }

    if (uniswap_base > 1e-12) {
        VenueBreakdown uniswap_leg_breakdown;
        try {
            if (is_buy) {
                uniswap_leg_breakdown = build_uniswap_buy_breakdown(uniswap_pool, uniswap_base);
            } else {
                uniswap_leg_breakdown = build_uniswap_sell_breakdown(uniswap_pool, uniswap_base);
            }
        } catch (...) {
            return result;
        }

        if (!uniswap_leg_breakdown.is_valid) {
            return result;
        }
        
        result.uniswap_leg = build_split_leg(Venue::Uniswap, uniswap_leg_breakdown, uniswap_ratio, uniswap_base);
    } else {
        result.uniswap_leg.is_used = false;
        result.uniswap_leg.ratio = 0.0;
        result.uniswap_leg.input_amount = 0.0;
    }

    result.is_valid = (result.binance_leg.is_used || result.uniswap_leg.is_used);
    if (!result.is_valid) {
        return result;
    }

    if (is_buy) {
        result.total_output_amount = total_base_amount;
        
        double total_raw_cost = 0.0;
        double total_net_cost = 0.0;
        double weighted_slippage = 0.0;
        double used_amount = 0.0;
        
        if (result.binance_leg.is_used) {
            total_raw_cost += result.binance_leg.breakdown.raw_cost;
            total_net_cost += result.binance_leg.breakdown.net_cost;
            weighted_slippage += result.binance_leg.breakdown.slippage_pct * result.binance_leg.input_amount;
            used_amount += result.binance_leg.input_amount;
        }
        if (result.uniswap_leg.is_used) {
            total_raw_cost += result.uniswap_leg.breakdown.raw_cost;
            total_net_cost += result.uniswap_leg.breakdown.net_cost;
            weighted_slippage += result.uniswap_leg.breakdown.slippage_pct * result.uniswap_leg.input_amount;
            used_amount += result.uniswap_leg.input_amount;
        }
        
        result.total_cost = total_net_cost;
        result.execution_price = (total_raw_cost > 1e-12) ? (total_raw_cost / total_base_amount) : 0.0;
        result.slippage_pct = (used_amount > 1e-12) ? (weighted_slippage / used_amount) : 0.0;
        result.unit_cost = (total_base_amount > 1e-12) ? (total_net_cost / total_base_amount) : 0.0;
    } else {
        result.total_output_amount = 0.0;
        double gross_proceeds = 0.0;
        double net_proceeds = 0.0;

        if (result.binance_leg.is_used) {
            gross_proceeds += result.binance_leg.breakdown.raw_proceeds;
            net_proceeds += result.binance_leg.breakdown.net_proceeds;
        }
        if (result.uniswap_leg.is_used) {
            gross_proceeds += result.uniswap_leg.breakdown.raw_proceeds;
            net_proceeds += result.uniswap_leg.breakdown.net_proceeds;
        }

        result.gross_proceeds = gross_proceeds;
        result.net_proceeds = net_proceeds;
        result.total_output_amount = net_proceeds;

        if (total_base_amount > 1e-12) {
            result.effective_proceeds = net_proceeds / total_base_amount;
            result.execution_price = gross_proceeds / total_base_amount;
        } else {
            result.effective_proceeds = 0.0;
            result.execution_price = 0.0;
        }

        double weighted_slippage = 0.0;
        double used_amount = 0.0;

        if (result.binance_leg.is_used) {
            weighted_slippage +=
                result.binance_leg.breakdown.slippage_pct * result.binance_leg.input_amount;
            used_amount += result.binance_leg.input_amount;
        }

        if (result.uniswap_leg.is_used) {
            weighted_slippage +=
                result.uniswap_leg.breakdown.slippage_pct * result.uniswap_leg.input_amount;
            used_amount += result.uniswap_leg.input_amount;
        }

        result.slippage_pct = (used_amount > 1e-12) ? (weighted_slippage / used_amount) : 0.0;
    }

    return result;
}

SplitResult Router::find_best_split(const OrderBook& binance_book,
                                    const UniswapV2Pool& uniswap_pool,
                                    TradeSide side,
                                    double total_base_amount) const {
    SplitResult best_split;
    best_split.is_valid = false;

    const bool is_buy = (side == TradeSide::Buy);

    for (int step = 0; step <= 20; ++step) {
        const double binance_ratio = static_cast<double>(step) / 20.0;

        SplitResult candidate = evaluate_split_candidate(
            binance_book,
            uniswap_pool,
            side,
            total_base_amount,
            binance_ratio
        );

        if (!candidate.is_valid) {
            continue;
        }

        if (!best_split.is_valid) {
            best_split = candidate;
            continue;
        }

        if (is_buy) {
            if (candidate.unit_cost < best_split.unit_cost ||
                (candidate.unit_cost == best_split.unit_cost &&
                 candidate.slippage_pct < best_split.slippage_pct)) {
                best_split = candidate;
            }
        } else {
            if (candidate.effective_proceeds > best_split.effective_proceeds) {
                best_split = candidate;
            } else if (candidate.effective_proceeds == best_split.effective_proceeds) {
                if (candidate.slippage_pct < best_split.slippage_pct) {
                    best_split = candidate;
                }
            }
        }
    }

    return best_split;
}

void Router::apply_best_single_venue(RouteResult& result) const {
    if (result.side == TradeSide::Buy) {
        if (!result.binance.is_valid || !result.uniswap.is_valid) {
            throw std::runtime_error("One or more buy-side venue quotes are invalid.");
        }

        result.routing_mode = RoutingMode::SingleVenue;

        if (result.binance.unit_cost <= result.uniswap.unit_cost) {
            result.best_venue = Venue::Binance;
            result.chosen = result.binance;
        } else {
            result.best_venue = Venue::Uniswap;
            result.chosen = result.uniswap;
        }

        result.expected_output = result.input_amount;
        result.execution_price = result.chosen.execution_price;
        result.slippage_pct = result.chosen.slippage_pct;
        result.total_cost = result.chosen.net_cost;
        result.unit_cost = result.chosen.unit_cost;
        result.gross_proceeds = 0.0;
        result.net_proceeds = 0.0;
        result.effective_proceeds = 0.0;
    } else {
        if (!result.binance.is_valid || !result.uniswap.is_valid) {
            throw std::runtime_error("One or more sell-side venue quotes are invalid.");
        }

        result.routing_mode = RoutingMode::SingleVenue;

        if (result.binance.effective_proceeds >= result.uniswap.effective_proceeds) {
            result.best_venue = Venue::Binance;
            result.chosen = result.binance;
        } else {
            result.best_venue = Venue::Uniswap;
            result.chosen = result.uniswap;
        }

        result.expected_output = result.chosen.output_amount;
        result.execution_price = result.chosen.execution_price;
        result.slippage_pct = result.chosen.slippage_pct;
        result.total_cost = 0.0;
        result.gross_proceeds = result.chosen.raw_proceeds;
        result.net_proceeds = result.chosen.net_proceeds;
        result.unit_cost = 0.0;
        result.effective_proceeds = result.chosen.effective_proceeds;
    }
}

void Router::maybe_apply_split_result(RouteResult& result,
                                      const SplitResult& split_result) const {
    result.split = split_result;

    if (!split_result.is_valid) {
        result.split_recommended = false;
        return;
    }

    if (result.side == TradeSide::Buy) {
        if (split_result.unit_cost < result.unit_cost) {
            result.split_recommended = true;
            result.routing_mode = RoutingMode::SplitOptimized;
            result.best_venue = Venue::Split;

            result.expected_output = result.input_amount;
            result.execution_price = split_result.execution_price;
            result.slippage_pct = split_result.slippage_pct;
            result.total_cost = split_result.total_cost;
            result.unit_cost = split_result.unit_cost;

            result.gross_proceeds = 0.0;
            result.net_proceeds = 0.0;
            result.effective_proceeds = 0.0;
        } else {
            result.split_recommended = false;
        }
    } else {
        if (split_result.effective_proceeds > result.effective_proceeds) {
            result.split_recommended = true;
            result.routing_mode = RoutingMode::SplitOptimized;
            result.best_venue = Venue::Split;

            result.expected_output = split_result.total_output_amount;
            result.execution_price = split_result.execution_price;
            result.slippage_pct = split_result.slippage_pct;

            result.total_cost = 0.0;
            result.gross_proceeds = split_result.gross_proceeds;
            result.net_proceeds = split_result.net_proceeds;
            result.unit_cost = 0.0;
            result.effective_proceeds = split_result.effective_proceeds;
        } else {
            result.split_recommended = false;
        }
    }

    result.split.improves_over_single = result.split_recommended;
}

RouteResult Router::find_best_route(const OrderBook& binance_book,
                                    const UniswapV2Pool& uniswap_pool,
                                    double base_amount,
                                    const std::string& side,
                                    bool enable_split) const {
    if (base_amount <= 0.0) {
        throw std::invalid_argument("base_amount must be greater than zero.");
    }

    const TradeSide trade_side = trade_side_from_string(side);

    RouteResult result;
    result.side = trade_side;
    result.input_amount = base_amount;
    result.routing_mode = RoutingMode::SingleVenue;
    result.split_evaluated = false;
    result.split_recommended = false;

    if (trade_side == TradeSide::Buy) {
        result.binance = build_binance_buy_breakdown(binance_book, base_amount);
        result.uniswap = build_uniswap_buy_breakdown(uniswap_pool, base_amount);
    } else {
        result.binance = build_binance_sell_breakdown(binance_book, base_amount);
        result.uniswap = build_uniswap_sell_breakdown(uniswap_pool, base_amount);
    }

    apply_best_single_venue(result);

    if (enable_split) {
        result.split_evaluated = true;
        const SplitResult split_result = find_best_split(
            binance_book,
            uniswap_pool,
            trade_side,
            base_amount
        );
        maybe_apply_split_result(result, split_result);
    }

    return result;
}