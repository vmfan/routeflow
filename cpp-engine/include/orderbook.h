#pragma once

#include <map>
#include <string>
#include <utility>
#include <functional>

class OrderBook {
public:
    struct Level {
        double price;
        double volume;
    };

    // One level per price is enough for MVP.
    // Bids: highest price first (descending).
    std::map<double, double, std::greater<double>> bids;

    // Asks: lowest price first (ascending).
    std::map<double, double> asks;

    std::string symbol;
    long timestamp = 0;

    void update(const std::string& side, double price, double volume);
    std::pair<double, double> bestBidAsk() const;

    // Returns total cost to buy `size` base units (e.g., ETH) using asks.
    // Returns -1 if not enough ask liquidity to fill the entire size.
    double simulateMarketBuy(double size) const;
    double simulateMarketSell(double size) const;
};