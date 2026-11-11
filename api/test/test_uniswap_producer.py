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

# --- metadata caching / block-timestamped staleness -----------------------------

import time as _time

from api.services import uniswap_pool_producer as producer


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def call(self, **kwargs):
        return self._fn(**kwargs)


class _FakePair:
    def __init__(self, counts, reserve_calls):
        class _Fns:
            def token0(_self):
                def _get(**kwargs):
                    counts["token0"] += 1
                    return "0x" + "0" * 39 + "1"

                return _Call(_get)

            def token1(_self):
                def _get(**kwargs):
                    counts["token1"] += 1
                    return "0x" + "0" * 39 + "2"

                return _Call(_get)

            def getReserves(_self):
                def _get(**kwargs):
                    reserve_calls.append(kwargs)
                    return (1_000 * 10**18, 3_000_000 * 10**6, 1_700_000_000)

                return _Call(_get)

        self.functions = _Fns()


class _FakeToken:
    def __init__(self, counts, symbol, decimals):
        class _Fns:
            def symbol(_self):
                def _get(**kwargs):
                    counts["symbol"] += 1
                    return symbol

                return _Call(_get)

            def decimals(_self):
                def _get(**kwargs):
                    counts["decimals"] += 1
                    return decimals

                return _Call(_get)

        self.functions = _Fns()


class _FakeEth:
    def __init__(self, counts, reserve_calls, block):
        self.counts = counts
        self.reserve_calls = reserve_calls
        self.block = block

    def contract(self, address, abi):
        if abi is producer.PAIR_ABI:
            return _FakePair(self.counts, self.reserve_calls)
        token = {"1": ("WETH", 18), "2": ("USDT", 6)}[address[-1]]
        return _FakeToken(self.counts, *token)

    def get_block(self, identifier):
        assert identifier == "latest"
        self.counts["get_block"] += 1
        return self.block


class _FakeW3:
    def __init__(self, block):
        from collections import Counter

        self.counts = Counter()
        self.reserve_calls = []
        self.eth = _FakeEth(self.counts, self.reserve_calls, block)


def test_pool_metadata_is_read_once_and_polls_only_call_get_reserves():
    w3 = _FakeW3({"number": 500, "timestamp": 1_700_000_100})

    metadata = producer.get_pool_metadata(w3, producer.PAIR_ADDRESS)
    producer.validate_pool_metadata(metadata)
    for _ in range(3):
        producer.fetch_pool_state(w3, producer.PAIR_ADDRESS, metadata)

    assert w3.counts["token0"] == 1
    assert w3.counts["token1"] == 1
    assert w3.counts["symbol"] == 2
    assert w3.counts["decimals"] == 2
    assert w3.counts["get_block"] == 3
    assert len(w3.reserve_calls) == 3


def test_fetch_pool_state_pins_reserves_to_the_fetched_block():
    w3 = _FakeW3({"number": 500, "timestamp": 1_700_000_100})
    metadata = producer.get_pool_metadata(w3, producer.PAIR_ADDRESS)

    state = producer.fetch_pool_state(w3, producer.PAIR_ADDRESS, metadata)

    assert w3.reserve_calls == [{"block_identifier": 500}]
    assert state["block_number"] == 500
    assert state["block_timestamp"] == 1_700_000_100
    assert state["block_timestamp_last"] == 1_700_000_000
    assert state["reserve0"] == 1000.0
    assert state["reserve1"] == 3_000_000.0


def test_validate_pool_metadata_rejects_unexpected_tokens():
    import pytest

    metadata = {"token0": {"symbol": "DAI"}, "token1": {"symbol": "USDT"}}

    with pytest.raises(RuntimeError, match="do not match"):
        producer.validate_pool_metadata(metadata)


def _pool_state(**overrides):
    state = {
        "pair_address": "0xpair",
        "token0": {"symbol": "WETH", "decimals": 18},
        "token1": {"symbol": "USDT", "decimals": 6},
        "reserve0": 1000.0,
        "reserve1": 3000000.0,
        "block_timestamp_last": 1_000,
    }
    state.update(overrides)
    return state


def test_snapshot_ts_ms_uses_block_timestamp_not_local_commit_time():
    block_ts = int(_time.time()) - 7

    payload = producer.normalize_for_routeflow("ETHUSDT", _pool_state(block_timestamp=block_ts, block_number=42))

    assert payload["snapshot_ts_ms"] == block_ts * 1000
    assert payload["source_event_ts_ms"] == block_ts * 1000
    assert payload["snapshot_ts"] == block_ts
    assert payload["block_number"] == 42
    assert payload["local_commit_ts_ms"] >= payload["snapshot_ts_ms"]


def test_snapshot_ts_ms_is_clamped_when_block_timestamp_is_in_the_future():
    future_ts = int(_time.time()) + 30

    payload = producer.normalize_for_routeflow("ETHUSDT", _pool_state(block_timestamp=future_ts))

    assert payload["snapshot_ts_ms"] <= payload["local_commit_ts_ms"]


def test_quiet_pool_is_not_aged_by_block_timestamp_last():
    block_ts = int(_time.time()) - 2

    payload = producer.normalize_for_routeflow(
        "ETHUSDT", _pool_state(block_timestamp=block_ts, block_timestamp_last=block_ts - 3600)
    )

    assert payload["snapshot_ts_ms"] == block_ts * 1000
