from api.services.uniswap_pool_producer import (_uniswap_snapshot_ts, normalize_for_routeflow, on_pool_committed)

def test_uniswap_snapshot_ts_from_block_timestamp_last():
    pool_state = {"block_timestamp_last": 1234567890}
    assert _uniswap_snapshot_ts(pool_state) == 1234567890

def test_normalize_pool_payload_includes_source_fields():
    pool_state = {
        "pair_address": "0xpair",
        "token0": {"symbol": "WETH", "decimals": 18},
        "token1": {"symbol": "USDT", "decimals": 6},
        "reserve0": 1000.0,
        "reserve1": 3000000.0,
        "block_timestamp_last": 1234567890,
    }

    payload = normalize_for_routeflow("ETHUSDT", pool_state)

    assert payload["source"] == "uniswap"
    assert payload["symbol"] == "ETHUSDT"
    assert payload["snapshot_ts"] == 1234567890
    assert "local_commit_ts_ms" in payload