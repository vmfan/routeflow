#include <gtest/gtest.h>

#include "orderbook.h"
#include "routing.h"
#include "route_result.hpp"
#include "uniswap_v2.h"

namespace {

OrderBook make_book_for_buy_split_benefit() {
    OrderBook book;
    book.symbol = "ETHUSDT";
    book.timestamp = 0;

    // Asks: first level good, second level much worse.
    book.update("ask", 100.0, 5.0);
    book.update("ask", 130.0, 5.0);

    // Bids just to keep book valid.
    book.update("bid", 99.0, 10.0);
    return book;
}

OrderBook make_book_for_sell_split_benefit() {
    OrderBook book;
    book.symbol = "ETHUSDT";
    book.timestamp = 0;

    // Bids: first level good, second level much worse.
    book.update("bid", 100.0, 5.0);
    book.update("bid", 70.0, 5.0);

    // Ask just to keep book valid.
    book.update("ask", 101.0, 10.0);
    return book;
}

OrderBook make_deep_book_no_split_needed() {
    OrderBook book;
    book.symbol = "ETHUSDT";
    book.timestamp = 0;

    // Deep, flat book so Binance stays competitive even for full size.
    book.update("ask", 100.0, 20.0);
    book.update("bid", 100.0, 20.0);
    return book;
}

UniswapV2Pool make_pool() {
    UniswapV2Pool pool;
    pool.reserve_token_a = 1000.0;
    pool.reserve_token_b = 100000.0;
    pool.fee_bps = 30.0;
    return pool;
}

}  // namespace

TEST(RouterSplitTest, BuySplitRecommendedOnlyWhenBetter) {
    const OrderBook book = make_book_for_buy_split_benefit();
    const UniswapV2Pool pool = make_pool();
    Router router(10.0, 0.0, 0.0);

    const double size = 10.0;

    const RouteResult single = router.find_best_route(book, pool, size, "buy", false);
    const RouteResult split = router.find_best_route(book, pool, size, "buy", true);

    EXPECT_FALSE(single.split_recommended);
    EXPECT_EQ(single.routing_mode, RoutingMode::SingleVenue);

    EXPECT_TRUE(split.split_evaluated);
    EXPECT_TRUE(split.split_recommended);
    EXPECT_EQ(split.routing_mode, RoutingMode::SplitOptimized);
    EXPECT_EQ(split.best_venue, Venue::Split);

    EXPECT_LT(split.unit_cost, single.unit_cost);
    EXPECT_LT(split.unit_cost, split.binance.unit_cost);
    EXPECT_LT(split.unit_cost, split.uniswap.unit_cost);

    EXPECT_TRUE(split.split.is_valid);
    EXPECT_TRUE(split.split.binance_leg.is_used);
    EXPECT_TRUE(split.split.uniswap_leg.is_used);
    EXPECT_GT(split.split.binance_leg.ratio, 0.0);
    EXPECT_LT(split.split.binance_leg.ratio, 1.0);
    EXPECT_NEAR(
        split.split.binance_leg.ratio + split.split.uniswap_leg.ratio,
        1.0,
        1e-9
    );
    EXPECT_TRUE(split.split.binance_leg.is_used);
    EXPECT_TRUE(split.split.uniswap_leg.is_used);
}

TEST(RouterSplitTest, BuySplitNotRecommendedWhenNoImprovement) {
    const OrderBook book = make_deep_book_no_split_needed();
    const UniswapV2Pool pool = make_pool();
    Router router(10.0, 0.0, 0.0);

    const double size = 4.0;

    const RouteResult single = router.find_best_route(book, pool, size, "buy", false);
    const RouteResult split = router.find_best_route(book, pool, size, "buy", true);

    EXPECT_TRUE(split.split_evaluated);
    EXPECT_FALSE(split.split_recommended);
    EXPECT_EQ(split.routing_mode, RoutingMode::SingleVenue);
    EXPECT_EQ(split.best_venue, single.best_venue);

    EXPECT_DOUBLE_EQ(split.unit_cost, single.unit_cost);
    EXPECT_DOUBLE_EQ(split.total_cost, single.total_cost);
}

TEST(RouterSplitTest, SellSplitRecommendedOnlyWhenBetter) {
    const OrderBook book = make_book_for_sell_split_benefit();
    const UniswapV2Pool pool = make_pool();
    Router router(10.0, 0.0, 0.0);

    const double size = 10.0;

    const RouteResult single = router.find_best_route(book, pool, size, "sell", false);
    const RouteResult split = router.find_best_route(book, pool, size, "sell", true);

    EXPECT_FALSE(single.split_recommended);
    EXPECT_EQ(single.routing_mode, RoutingMode::SingleVenue);

    EXPECT_TRUE(split.split_evaluated);
    EXPECT_TRUE(split.split_recommended);
    EXPECT_EQ(split.routing_mode, RoutingMode::SplitOptimized);
    EXPECT_EQ(split.best_venue, Venue::Split);

    EXPECT_GT(split.effective_proceeds, single.effective_proceeds);
    EXPECT_GT(split.effective_proceeds, split.binance.effective_proceeds);
    EXPECT_GT(split.effective_proceeds, split.uniswap.effective_proceeds);

    EXPECT_TRUE(split.split.is_valid);
    EXPECT_TRUE(split.split.binance_leg.is_used);
    EXPECT_TRUE(split.split.uniswap_leg.is_used);
    EXPECT_GT(split.split.binance_leg.ratio, 0.0);
    EXPECT_LT(split.split.binance_leg.ratio, 1.0);
    EXPECT_NEAR(
        split.split.binance_leg.ratio + split.split.uniswap_leg.ratio,
        1.0,
        1e-9
    );
    EXPECT_TRUE(split.split.binance_leg.is_used);
    EXPECT_TRUE(split.split.uniswap_leg.is_used);
}

TEST(RouterSplitTest, SellSplitNotRecommendedWhenNoImprovement) {
    const OrderBook book = make_deep_book_no_split_needed();
    const UniswapV2Pool pool = make_pool();
    Router router(10.0, 0.0, 0.0);

    const double size = 4.0;

    const RouteResult single = router.find_best_route(book, pool, size, "sell", false);
    const RouteResult split = router.find_best_route(book, pool, size, "sell", true);

    EXPECT_TRUE(split.split_evaluated);
    EXPECT_FALSE(split.split_recommended);
    EXPECT_EQ(split.routing_mode, RoutingMode::SingleVenue);
    EXPECT_EQ(split.best_venue, single.best_venue);

    EXPECT_DOUBLE_EQ(split.effective_proceeds, single.effective_proceeds);
    EXPECT_DOUBLE_EQ(split.net_proceeds, single.net_proceeds);
}