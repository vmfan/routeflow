#include "orderbook.h"
#include <cassert>
#include <iostream>

int main() {
    OrderBook ob;

    // Test update + bestBidAsk. [file:1]
    ob.update("bid", 100.0, 2.0);
    ob.update("bid",  99.0, 1.0);
    ob.update("ask", 101.0, 5.0);
    ob.update("ask", 102.0, 1.0);

    auto [bid, ask] = ob.bestBidAsk();
    assert(bid == 100.0);
    assert(ask == 101.0);

    // Test delete behavior when volume == 0. [file:1]
    ob.update("bid", 100.0, 0.0);
    auto [bid2, ask2] = ob.bestBidAsk();
    assert(bid2 == 99.0);
    assert(ask2 == 101.0);

    // Test slippage/cost simulation for market buy (walk asks). [file:1]
    // Current asks: 101@5, 102@1
    double cost = ob.simulateMarketBuy(6.0); // 5 at 101 + 1 at 102 = 505 + 102 = 607
    assert(cost == 607.0);

    // Test insufficient liquidity returns -1. [file:1]
    double costFail = ob.simulateMarketBuy(7.0); // only 6 available
    assert(costFail == -1.0);

    std::cout << "All tests pass\n";
    return 0;
}