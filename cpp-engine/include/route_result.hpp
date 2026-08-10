#pragma once

#include <string>
#include <stdexcept>

enum class TradeSide {
    Buy,
    Sell
};

enum class Venue {
    Binance,
    Uniswap,
    Split,   // synthetic top-level route outcome, not a literal venue
    Unknown
};

enum class RoutingMode {
    SingleVenue,
    SplitOptimized
};

inline std::string to_string(TradeSide side) {
    switch (side) {
        case TradeSide::Buy:  return "buy";
        case TradeSide::Sell: return "sell";
        default:              return "unknown";
    }
}

inline TradeSide trade_side_from_string(const std::string& side) {
    if (side == "buy") {
        return TradeSide::Buy;
    }
    if (side == "sell") {
        return TradeSide::Sell;
    }
    throw std::invalid_argument("side must be 'buy' or 'sell'.");
}

inline std::string to_string(Venue venue) {
    switch (venue) {
        case Venue::Binance: return "Binance";
        case Venue::Uniswap: return "Uniswap";
        case Venue::Split:   return "Split";
        default:             return "Unknown";
    }
}

inline std::string to_string(RoutingMode mode) {
    switch (mode) {
        case RoutingMode::SingleVenue:    return "single_venue";
        case RoutingMode::SplitOptimized: return "split_optimized";
        default:                          return "unknown";
    }
}

struct VenueBreakdown {
    Venue venue = Venue::Unknown;

    // Common execution info
    double input_amount = 0.0;
    double output_amount = 0.0;
    double execution_price = 0.0;
    double slippage_pct = 0.0;

    // Buy-side economics
    double raw_cost = 0.0;
    double net_cost = 0.0;
    double unit_cost = 0.0;

    // Sell-side economics
    double raw_proceeds = 0.0;
    double net_proceeds = 0.0;
    double effective_proceeds = 0.0;

    // CEX-specific diagnostics
    double best_bid = 0.0;
    double best_ask = 0.0;

    // AMM-specific diagnostics
    double mid_price = 0.0;
    double amount_in = 0.0;
    double amount_out = 0.0;
    double price_impact_pct = 0.0;

    // Gas / extra execution costs
    double gas_cost_native = 0.0;
    double gas_cost_quote = 0.0;
    double gas_cost_per_unit = 0.0;

    bool is_valid = false;
};

struct SplitLeg {
    Venue venue = Venue::Unknown;
    double ratio = 0.0;          // fraction of the parent order routed to this venue
    double input_amount = 0.0;   // base amount assigned to this venue
    VenueBreakdown breakdown;
    bool is_used = false;
};

struct SplitResult {
    bool improves_over_single = false;
    bool is_valid = false;

    double total_input_amount = 0.0;
    double total_output_amount = 0.0;
    double execution_price = 0.0;
    double slippage_pct = 0.0;

    // Buy-side aggregate economics
    double total_cost = 0.0;      // quote paid after fees/gas
    double unit_cost = 0.0;       // total_cost / total_output_amount

    // Sell-side aggregate economics
    double gross_proceeds = 0.0;
    double net_proceeds = 0.0;
    double effective_proceeds = 0.0;

    SplitLeg binance_leg;
    SplitLeg uniswap_leg;
};

struct RouteResult {
    TradeSide side = TradeSide::Buy;
    RoutingMode routing_mode = RoutingMode::SingleVenue;
    Venue best_venue = Venue::Unknown;

    // Canonical top-level route output
    double input_amount = 0.0;
    double expected_output = 0.0;
    double execution_price = 0.0;
    double slippage_pct = 0.0;

    // Top-level economic summary
    double total_cost = 0.0;
    double gross_proceeds = 0.0;
    double net_proceeds = 0.0;

    // Canonical comparison metrics
    double unit_cost = 0.0;
    double effective_proceeds = 0.0;

    // Venue-level diagnostics
    VenueBreakdown chosen;
    VenueBreakdown binance;
    VenueBreakdown uniswap;

    // Split-optimization diagnostics
    bool split_evaluated = false;
    bool split_recommended = false;
    SplitResult split;
};