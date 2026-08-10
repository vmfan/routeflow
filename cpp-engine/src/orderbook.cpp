#include "orderbook.h"

#include <algorithm>
#include <chrono>
#include <stdexcept>

void OrderBook::update(const std::string& side, double price, double volume) {
    // Update rule from the plan: if volume == 0, remove that price level. [file:1]
    if (side == "bid") {
        if (volume == 0) {
            bids.erase(price);
        } else {
            bids[price] = volume;
        }
    } else if (side == "ask") {
        if (volume == 0) {
            asks.erase(price);
        } else {
            asks[price] = volume;
        }
    } else {
        throw std::invalid_argument("side must be 'bid' or 'ask'.");
    }

    // Timestamp update as in the plan (track “last updated”). [file:1]
    timestamp = static_cast<long>(
        std::chrono::system_clock::now().time_since_epoch().count()
    );
}

std::pair<double, double> OrderBook::bestBidAsk() const {
    // Plan behavior: return 0 if empty. [file:1]
    double bestBid = bids.empty() ? 0.0 : bids.begin()->first; // descending map => begin is max
    double bestAsk = asks.empty() ? 0.0 : asks.begin()->first; // ascending map => begin is min
    return {bestBid, bestAsk};
}

double OrderBook::simulateMarketBuy(double size) const {
    if (size <= 0.0) {
        throw std::invalid_argument("size must be greater than zero.");
    }

    double totalCost = 0.0;
    double remaining = size;
    constexpr double EPS = 1e-12;

    for (const auto& level : asks) {
        const double price = level.first;
        const double volume = level.second;

        if (volume <= 0.0) {
            continue;
        }

        const double fill = std::min(remaining, volume);
        totalCost += fill * price;
        remaining -= fill;

        if (remaining <= EPS) {
            return totalCost;
        }
    }

    return -1.0;
}

double OrderBook::simulateMarketSell(double size) const {
    if (size <= 0.0) {
        throw std::invalid_argument("size must be greater than zero.");
    }

    double totalProceeds = 0.0;
    double remaining = size;
    constexpr double EPS = 1e-12;

    for (const auto& level : bids) {
        const double price = level.first;
        const double volume = level.second;

        if (volume <= 0.0) {
            continue;
        }

        const double fill = std::min(remaining, volume);
        totalProceeds += fill * price;
        remaining -= fill;

        if (remaining <= EPS) {
            return totalProceeds;
        }
    }

    return -1.0;
}