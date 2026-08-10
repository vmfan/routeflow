from api.explainability import explain
from api.models import Explanation

def _base_buy_route(**overrides):
    payload = {
        "venue": "binance",
        "input_amount": 5.0,
        "expected_output": 5.0,
        "execution_price": 2500.0,
        "slippage_pct": 0.0200,
        "total_cost": 12500.0,
        "unit_cost": 2500.0,
        "cex_slippage_pct": 0.0200,
        "dex_price_impact_pct": 0.5000,
    }
    payload.update(overrides)
    return payload


def _base_sell_route(**overrides):
    payload = {
        "venue": "uniswap",
        "input_amount": 5.0,
        "expected_output": 12480.0,
        "execution_price": 2496.0,
        "slippage_pct": 0.0300,
        "gross_proceeds": 12490.0,
        "net_proceeds": 12480.0,
        "effective_proceeds": 2496.0,
        "cex_slippage_pct": 0.0100,
        "dex_price_impact_pct": 0.0400,
    }
    payload.update(overrides)
    return payload


def _split_result(**overrides):
    payload = {
        "is_valid": True,
        "improves_over_single": True,
        "total_input_amount": 5.0,
        "total_output_amount": 5.0,
        "execution_price": 2498.0,
        "slippage_pct": 0.0150,
        "total_cost": 12490.0,
        "unit_cost": 2498.0,
        "binance_leg": {
            "ratio": 0.60,
            "input_amount": 3.0,
            "is_used": True,
        },
        "uniswap_leg": {
            "ratio": 0.40,
            "input_amount": 2.0,
            "is_used": True,
        },
    }
    payload.update(overrides)
    return payload


def test_split_wins_branch():
    best_route = _base_buy_route()
    split = _split_result()

    explanation = explain(best_route, split)

    assert isinstance(explanation, Explanation)
    assert explanation.decision_key == "split_wins"
    assert explanation.title == "Split route selected"
    assert explanation.recommended_venue == "split"
    assert explanation.recommended_split_ratio_binance == 0.60
    assert explanation.recommended_split_ratio_uniswap == 0.40


def test_near_tie_branch():
    best_route = _base_buy_route(
        unit_cost=2500.0,
        total_cost=12500.0,
        binance_unit_cost=2500.0,
        uniswap_unit_cost=2502.0,
    )
    split = _split_result(improves_over_single=False, unit_cost=2502.0, total_cost=12501.0)

    explanation = explain(best_route, split)

    assert explanation.decision_key == "near_tie"
    assert explanation.title == "Near tie"
    assert "Venue difference" in explanation.details[0]


def test_cex_wins_dex_impact_branch():
    best_route = _base_buy_route(
        venue="binance",
        cex_slippage_pct=0.0200,
        dex_price_impact_pct=0.8000,
    )
    split = _split_result(improves_over_single=False, unit_cost=2600.0, total_cost=13000.0)

    explanation = explain(best_route, split)

    assert explanation.decision_key == "cex_wins_dex_impact"
    assert explanation.title == "Binance selected"
    assert "Uniswap price impact" in explanation.details[0]


def test_cex_wins_both_low_branch():
    best_route = _base_buy_route(
        venue="binance",
        cex_slippage_pct=0.0200,
        dex_price_impact_pct=0.0500,
    )
    split = _split_result(improves_over_single=False, unit_cost=2550.0, total_cost=12750.0)

    explanation = explain(best_route, split)

    assert explanation.decision_key == "cex_wins_both_low"
    assert explanation.title == "Binance selected"
    assert "Binance slippage" in explanation.details[1]


def test_dex_wins_branch():
    best_route = _base_sell_route(venue="uniswap")
    split = None

    explanation = explain(best_route, split)

    assert explanation.decision_key == "dex_wins"
    assert explanation.title == "Uniswap selected"
    assert explanation.recommended_venue == "uniswap"


def test_warning_appended():
    best_route = _base_buy_route()
    split = _split_result()

    explanation = explain(best_route, split)

    assert explanation.warnings
    assert "cached snapshot remains executable" in explanation.warnings[0].lower()


def test_explanation_is_deterministic():
    best_route = _base_buy_route()
    split = _split_result()

    explanation_a = explain(best_route, split)
    explanation_b = explain(best_route, split)

    assert explanation_a == explanation_b


def test_no_unfilled_placeholders_in_output():
    best_route = _base_buy_route()
    split = _split_result()

    explanation = explain(best_route, split)

    assert "{" not in explanation.title
    assert "{" not in explanation.summary
    for detail in explanation.details:
        assert "{" not in detail