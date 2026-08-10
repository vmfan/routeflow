from api.models import Explanation

from api import cli

class DummyResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} error", response=self)
        
def fake_explain(best_route, split_result=None):
    return Explanation(
        decision_key="cex_wins_dex_impact",
        title="Binance selected",
        summary="Binance wins because Uniswap price impact is materially higher.",
        details=["Uniswap price impact: 0.0500%.", "Binance slippage: 0.0100%."],
        warnings=["Displayed results assume the cached snapshot remains executable at quote time."],
        recommended_venue="binance",
        recommended_split_ratio_binance=None,
        recommended_split_ratio_uniswap=None,
    )


def fake_format_route_report(data, explanation):
    return (
        "RouteFlow Quote — ETHUSDT buy 1.0\n"
        "Recommendation: Binance selected\n"
        "Selected route: Binance\n"
        "Binance wins because Uniswap price impact is materially higher."
    )
        
def test_cli_prints_stale_data_message(monkeypatch, capsys):
    def fake_post(url, json, timeout):
        return DummyResponse(
            503,
            {
                "detail": "Cached market data is stale.",
                "symbol": "ETHUSDT",
                "source": "Binance",
                "age_ms": 9000,
                "max_age_ms": 5000,
            },
        )

    monkeypatch.setattr(cli.requests, "post", fake_post)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "--symbol", "ETHUSDT",
            "--side", "buy",
            "--size", "1.0",
        ],
    )

    exit_code = cli.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "STALE DATA: ETHUSDT on Binance is too old to trust" in captured.err
    assert "age=9000ms" in captured.err
    assert "limit=5000ms" in captured.err

def test_cli_prints_generic_error_message(monkeypatch, capsys):
    def fake_post(url, json, timeout):
        return DummyResponse(
            400,
            {"detail": "This route endpoint supports side='buy' or side='sell' only."},
        )

    monkeypatch.setattr(cli.requests, "post", fake_post)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "--symbol", "ETHUSDT",
            "--side", "buy",
            "--size", "1.0",
        ],
    )

    exit_code = cli.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ERROR: This route endpoint supports side='buy' or side='sell' only." in captured.err

def test_cli_prints_connection_error(monkeypatch, capsys):
    def fake_post(url, json, timeout):
        raise cli.requests.RequestException("connection refused")

    monkeypatch.setattr(cli.requests, "post", fake_post)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "--symbol", "ETHUSDT",
            "--side", "sell",
            "--size", "2.0",
        ],
    )

    exit_code = cli.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ERROR: could not reach API: connection refused" in captured.err

def test_cli_prints_success_json(monkeypatch, capsys):
    payload = {
        "symbol": "ETHUSDT",
        "side": "buy",
        "input_amount": 1.0,
        "best_route": {
            "venue": "Binance",
            "input_amount": 1.0,
            "expected_output": 1.0,
            "execution_price": 3001.0,
            "slippage_pct": 0.01,
            "total_cost": 3004.001,
            "unit_cost": 3004.001,
        },
        "routing_mode": "SingleVenue",
        "split_evaluated": False,
        "split_recommended": False,
        "binance": {
            "venue": "Binance",
            "input_amount": 1.0,
            "output_amount": 3001.0,
            "execution_price": 3001.0,
            "slippage_pct": 0.01,
            "best_bid": 3000.0,
            "best_ask": 3001.0,
            "raw_cost": 3001.0,
            "net_cost": 3004.001,
            "unit_cost": 3004.001,
        },
        "uniswap": {
            "venue": "Uniswap",
            "input_amount": 3003.0,
            "output_amount": 1.0,
            "execution_price": 3003.0,
            "slippage_pct": 0.05,
            "mid_price": 3000.0,
            "price_impact_pct": 0.05,
            "gas_cost_native": 0.00022,
            "gas_cost_quote": 0.66,
            "gas_cost_per_unit": 0.66,
            "raw_cost": 3003.0,
            "net_cost": 3003.66,
            "unit_cost": 3003.66,
        },
    }

    def fake_post(url, json, timeout):
        return DummyResponse(200, payload)

    monkeypatch.setattr(cli.requests, "post", fake_post)
    monkeypatch.setattr(cli, "explain", fake_explain)
    monkeypatch.setattr(cli, "format_route_report", fake_format_route_report)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "--symbol", "ETHUSDT",
            "--side", "buy",
            "--size", "1.0",
        ],
    )

    exit_code = cli.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "RouteFlow Quote — ETHUSDT buy 1.0" in captured.out
    assert "Recommendation: Binance selected" in captured.out
    assert "Selected route: Binance" in captured.out
    assert "Binance wins because Uniswap price impact is materially higher." in captured.out

def test_cli_handles_non_json_503_response(monkeypatch, capsys):
    class NonJsonResponse(DummyResponse):
        def json(self):
            raise ValueError("not json")

    def fake_post(url, json, timeout):
        return NonJsonResponse(503, text="Service unavailable")

    monkeypatch.setattr(cli.requests, "post", fake_post)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "--symbol", "ETHUSDT",
            "--side", "buy",
            "--size", "1.0",
        ],
    )

    exit_code = cli.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "STALE DATA:" in captured.err

def test_cli_prints_formatted_split_report(monkeypatch, capsys):
    payload = {
        "symbol": "ETHUSDT",
        "side": "buy",
        "input_amount": 1.0,
        "best_route": {
            "venue": None,
            "input_amount": 1.0,
            "expected_output": 1.0,
            "execution_price": 3000.5,
            "slippage_pct": 0.01,
            "total_cost": 3000.5,
            "unit_cost": 3000.5,
            "cex_slippage_pct": 0.01,
            "dex_price_impact_pct": 0.04,
        },
        "routing_mode": "SplitOptimized",
        "split_evaluated": True,
        "split_recommended": True,
        "split": {
            "is_valid": True,
            "improves_over_single": True,
            "total_input_amount": 1.0,
            "total_output_amount": 1.0,
            "execution_price": 3000.5,
            "slippage_pct": 0.01,
            "total_cost": 3000.5,
            "unit_cost": 3000.5,
            "binance_leg": {
                "ratio": 0.6,
                "input_amount": 0.6,
                "is_used": True,
            },
            "uniswap_leg": {
                "ratio": 0.4,
                "input_amount": 0.4,
                "is_used": True,
            },
        },
        "binance": {
            "venue": "Binance",
            "input_amount": 1.0,
            "output_amount": 3001.0,
            "execution_price": 3001.0,
            "slippage_pct": 0.01,
            "best_bid": 3000.0,
            "best_ask": 3001.0,
            "raw_cost": 3001.0,
            "net_cost": 3004.001,
            "unit_cost": 3004.001,
        },
        "uniswap": {
            "venue": "Uniswap",
            "input_amount": 3003.0,
            "output_amount": 1.0,
            "execution_price": 3003.0,
            "slippage_pct": 0.05,
            "mid_price": 3000.0,
            "price_impact_pct": 0.05,
            "gas_cost_native": 0.00022,
            "gas_cost_quote": 0.66,
            "gas_cost_per_unit": 0.66,
            "raw_cost": 3003.0,
            "net_cost": 3003.66,
            "unit_cost": 3003.66,
        },
    }

    def fake_post(url, json, timeout):
        return DummyResponse(200, payload)

    def fake_explain_split(best_route, split_result=None):
        return Explanation(
            decision_key="split_wins",
            title="Split route selected",
            summary="A split order reduces overall execution cost versus any single venue.",
            details=["Binance allocation: 60.00%.", "Uniswap allocation: 40.00%."],
            warnings=[],
            recommended_venue="split",
            recommended_split_ratio_binance=0.6,
            recommended_split_ratio_uniswap=0.4,
        )

    def fake_format_route_report_split(data, explanation):
        return (
            "RouteFlow Quote — ETHUSDT buy 1.0\n"
            "Recommendation: Split route selected\n"
            "Selected route: split\n"
            "A split order reduces overall execution cost versus any single venue."
        )

    monkeypatch.setattr(cli.requests, "post", fake_post)
    monkeypatch.setattr(cli, "explain", fake_explain_split)
    monkeypatch.setattr(cli, "format_route_report", fake_format_route_report_split)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "--symbol", "ETHUSDT",
            "--side", "buy",
            "--size", "1.0",
            "--enable-split",
        ],
    )

    exit_code = cli.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Recommendation: Split route selected" in captured.out
    assert "Selected route: split" in captured.out