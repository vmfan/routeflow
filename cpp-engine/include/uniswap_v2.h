#pragma once

struct SwapResult {
    double amount_in = 0.0;
    double amount_out = 0.0;
    double execution_price = 0.0;
    double price_impact_pct = 0.0;
    double unit_cost = 0.0;

    double gas_cost_native = 0.0;
    double gas_cost_quote = 0.0;
};

class UniswapV2Pool {
public:
    double reserve_token_a = 0.0;
    double reserve_token_b = 0.0;
    double fee_bps = 30.0;

    double get_amount_out(double amount_in, double reserve_in, double reserve_out) const;
    double get_amount_in(double amount_out, double reserve_in, double reserve_out) const;

    double get_amount_out_a_to_b(double amount_in) const;
    double get_amount_out_b_to_a(double amount_in) const;
    double get_amount_in_a_to_b(double amount_out) const;
    double get_amount_in_b_to_a(double amount_out) const;

    double mid_price_a_in_b() const;
    double mid_price_b_in_a() const;

    double compute_gas_adjusted_effective_cost(double execution_price,
                                           double gas_cost_quote,
                                           double amount_out) const;

    SwapResult estimate_swap_exact_in(double amount_in,
                                      double reserve_in,
                                      double reserve_out) const;

    SwapResult estimate_swap_exact_out(double amount_out,
                                       double reserve_in,
                                       double reserve_out) const;

    SwapResult estimate_swap_a_to_b(double amount_in) const;
    SwapResult estimate_swap_b_to_a(double amount_in) const;

    SwapResult estimate_buy_a_with_b(double amount_out_a) const;
    SwapResult estimate_buy_b_with_a(double amount_out_b) const;

private:
    void validate_pool(double reserve_in, double reserve_out) const;
    void validate_amount_in(double amount_in) const;
    double compute_price_impact_pct(double execution_price,
                                    double mid_price) const;
    double compute_price_impact_pct_sell(double execution_price,
                                        double mid_price) const;
};