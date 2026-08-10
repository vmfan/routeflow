#include "uniswap_v2.h"

#include <algorithm>
#include <stdexcept>

void UniswapV2Pool::validate_pool(double reserve_in, double reserve_out) const {
    if (reserve_in <= 0.0 || reserve_out <= 0.0) {
        throw std::invalid_argument("Pool reserves must be greater than zero.");
    }
}

void UniswapV2Pool::validate_amount_in(double amount_in) const {
    if (amount_in <= 0.0) {
        throw std::invalid_argument("Input amount must be greater than zero.");
    }
}

double UniswapV2Pool::get_amount_out(double amount_in, double reserve_in, double reserve_out) const {
    validate_amount_in(amount_in);
    validate_pool(reserve_in, reserve_out);

    const double fee_multiplier = (10000.0 - fee_bps) / 10000.0;
    const double amount_in_with_fee = amount_in * fee_multiplier;

    const double numerator = amount_in_with_fee * reserve_out;
    const double denominator = reserve_in + amount_in_with_fee;

    if (denominator <= 0.0) {
        throw std::runtime_error("Invalid denominator in get_amount_out.");
    }

    return numerator / denominator;
}

double UniswapV2Pool::get_amount_in(double amount_out, double reserve_in, double reserve_out) const {
    validate_pool(reserve_in, reserve_out);

    if (amount_out <= 0.0) {
        throw std::invalid_argument("Output amount must be greater than zero.");
    }

    if (amount_out >= reserve_out) {
        throw std::invalid_argument("Requested output amount is too large for pool liquidity.");
    }

    const double fee_multiplier = (10000.0 - fee_bps) / 10000.0;
    const double numerator = reserve_in * amount_out;
    const double denominator = (reserve_out - amount_out) * fee_multiplier;

    if (denominator <= 0.0) {
        throw std::runtime_error("Invalid denominator in get_amount_in.");
    }

    return numerator / denominator;
}

double UniswapV2Pool::get_amount_out_a_to_b(double amount_in) const {
    return get_amount_out(amount_in, reserve_token_a, reserve_token_b);
}

double UniswapV2Pool::get_amount_out_b_to_a(double amount_in) const {
    return get_amount_out(amount_in, reserve_token_b, reserve_token_a);
}

double UniswapV2Pool::get_amount_in_a_to_b(double amount_out) const {
    return get_amount_in(amount_out, reserve_token_a, reserve_token_b);
}

double UniswapV2Pool::get_amount_in_b_to_a(double amount_out) const {
    return get_amount_in(amount_out, reserve_token_b, reserve_token_a);
}

double UniswapV2Pool::mid_price_a_in_b() const {
    validate_pool(reserve_token_a, reserve_token_b);
    return reserve_token_b / reserve_token_a;
}

double UniswapV2Pool::mid_price_b_in_a() const {
    validate_pool(reserve_token_a, reserve_token_b);
    return reserve_token_a / reserve_token_b;
}

double UniswapV2Pool::compute_price_impact_pct(double execution_price,
                                               double mid_price) const {
    if (mid_price <= 0.0) {
        throw std::runtime_error("Invalid mid price.");
    }

    const double impact = ((execution_price - mid_price) / mid_price) * 100.0;
    return std::max(0.0, impact);
}

double UniswapV2Pool::compute_price_impact_pct_sell(double execution_price,
                                                    double mid_price) const {
    if (mid_price <= 0.0) {
        throw std::runtime_error("Invalid mid price.");
    }

    const double impact = ((mid_price - execution_price) / mid_price) * 100.0;
    return std::max(0.0, impact);
}

double UniswapV2Pool::compute_gas_adjusted_effective_cost(double execution_price,
                                                          double gas_cost_quote,
                                                          double amount_out) const {
    if (execution_price < 0.0) {
        throw std::invalid_argument("execution_price must be non-negative.");
    }

    if (gas_cost_quote < 0.0) {
        throw std::invalid_argument("gas_cost_quote must be non-negative.");
    }

    if (amount_out <= 0.0) {
        throw std::invalid_argument("amount_out must be greater than zero.");
    }

    const double gas_cost_per_unit = gas_cost_quote / amount_out;
    return execution_price + gas_cost_per_unit;
}

SwapResult UniswapV2Pool::estimate_swap_exact_in(double amount_in,
                                                 double reserve_in,
                                                 double reserve_out) const {
    const double amount_out = get_amount_out(amount_in, reserve_in, reserve_out);
    const double execution_price = amount_out / amount_in;
    const double mid_price = reserve_out / reserve_in;
    const double price_impact_pct = compute_price_impact_pct_sell(execution_price, mid_price);

    SwapResult result;
    result.amount_in = amount_in;
    result.amount_out = amount_out;
    result.execution_price = execution_price;
    result.price_impact_pct = price_impact_pct;
    result.unit_cost = execution_price;
    result.gas_cost_native = 0.0;
    result.gas_cost_quote = 0.0;
    return result;
}

SwapResult UniswapV2Pool::estimate_swap_exact_out(double amount_out,
                                                  double reserve_in,
                                                  double reserve_out) const {
    const double amount_in = get_amount_in(amount_out, reserve_in, reserve_out);
    const double execution_price = amount_in / amount_out;
    const double mid_price = reserve_in / reserve_out;
    const double price_impact_pct = compute_price_impact_pct(execution_price, mid_price);

    SwapResult result;
    result.amount_in = amount_in;
    result.amount_out = amount_out;
    result.execution_price = execution_price;
    result.price_impact_pct = price_impact_pct;
    result.unit_cost = execution_price;
    result.gas_cost_native = 0.0;
    result.gas_cost_quote = 0.0;
    return result;
}

SwapResult UniswapV2Pool::estimate_swap_a_to_b(double amount_in) const {
    return estimate_swap_exact_in(amount_in, reserve_token_a, reserve_token_b);
}

SwapResult UniswapV2Pool::estimate_swap_b_to_a(double amount_in) const {
    return estimate_swap_exact_in(amount_in, reserve_token_b, reserve_token_a);
}

SwapResult UniswapV2Pool::estimate_buy_a_with_b(double amount_out_a) const {
    return estimate_swap_exact_out(amount_out_a, reserve_token_b, reserve_token_a);
}

SwapResult UniswapV2Pool::estimate_buy_b_with_a(double amount_out_b) const {
    return estimate_swap_exact_out(amount_out_b, reserve_token_a, reserve_token_b);
}