from .models import Explanation

NEAR_TIE_THRESHOLD_PCT = 0.10
LOW_IMPACT_THRESHOLD_PCT = 0.20

TEMPLATES = {
    "split_wins": {
        "title": "Split route selected",
        "summary": "A split order reduces overall execution cost versus any single venue.",
    },
    "cex_wins_dex_impact": {
        "title": "Binance selected",
        "summary": "Binance wins because Uniswap price impact is materially higher.",
    },
    "cex_wins_both_low": {
        "title": "Binance selected",
        "summary": "Binance is cheaper even though both venues have low market impact.",
    },
    "dex_wins": {
        "title": "Uniswap selected",
        "summary": "Uniswap offers better execution after accounting for gas and impact.",
    },
    "near_tie": {
        "title": "Near tie",
        "summary": "Both venues are priced very closely for this trade size.",
    },
}

WARNING_TEMPLATES = {
    "partial_fill_warning": "Displayed results assume the cached snapshot remains executable at quote time.",
}

def _compute_cost_diff_pct(best_value: float, alt_value: float) -> float:
    if alt_value == 0:
        return 0.0
    return abs(best_value - alt_value) / abs(alt_value) * 100.0

def _safe_number(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_buy(best_route: dict) -> bool:
    return best_route.get("total_cost") is not None or best_route.get("unit_cost") is not None


def _best_value(best_route: dict, is_buy: bool) -> float:
    if is_buy:
        if best_route.get("unit_cost") is not None:
            return _safe_number(best_route.get("unit_cost"))
        return _safe_number(best_route.get("total_cost"))
    if best_route.get("effective_proceeds") is not None:
        return _safe_number(best_route.get("effective_proceeds"))
    return _safe_number(best_route.get("net_proceeds"))


def _safe_optional_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _alternative_venue_value(best_route: dict, is_buy: bool):
    venue = (best_route.get("venue") or "").lower()

    if is_buy:
        binance_value = _safe_optional_number(best_route.get("binance_unit_cost"))
        uniswap_value = _safe_optional_number(best_route.get("uniswap_unit_cost"))
    else:
        binance_value = _safe_optional_number(best_route.get("binance_effective_proceeds"))
        uniswap_value = _safe_optional_number(best_route.get("uniswap_effective_proceeds"))

    if venue == "binance":
        return uniswap_value
    if venue == "uniswap":
        return binance_value
    return None


def _warning_list() -> list[str]:
    return [WARNING_TEMPLATES["partial_fill_warning"]]


def explain(best_route: dict, split_result: dict | None = None) -> Explanation:
    is_buy = _is_buy(best_route)
    venue = (best_route.get("venue") or "").lower()

    best_value = _best_value(best_route, is_buy)

    comparison_value = None
    split_improves = bool(split_result and split_result.get("improves_over_single"))

    if split_improves:
        if is_buy:
            if split_result.get("unit_cost") is not None:
                comparison_value = _safe_number(split_result.get("unit_cost"))
            elif split_result.get("total_cost") is not None:
                comparison_value = _safe_number(split_result.get("total_cost"))
        else:
            if split_result.get("effective_proceeds") is not None:
                comparison_value = _safe_number(split_result.get("effective_proceeds"))
            elif split_result.get("net_proceeds") is not None:
                comparison_value = _safe_number(split_result.get("net_proceeds"))

    if comparison_value is None:
        comparison_value = _alternative_venue_value(best_route, is_buy)

    cost_diff_pct = None
    if comparison_value is not None:
        cost_diff_pct = _compute_cost_diff_pct(best_value, comparison_value)

    if split_improves:
        binance_ratio = _safe_number((split_result.get("binance_leg") or {}).get("ratio"), 0.0)
        uniswap_ratio = _safe_number((split_result.get("uniswap_leg") or {}).get("ratio"), 0.0)
        template = TEMPLATES["split_wins"]
        details = [
            f"Binance allocation: {binance_ratio * 100:.2f}%.",
            f"Uniswap allocation: {uniswap_ratio * 100:.2f}%.",
        ]
        return Explanation(
            decision_key="split_wins",
            title=template["title"],
            summary=template["summary"],
            details=details,
            warnings=_warning_list(),
            recommended_venue="split",
            recommended_split_ratio_binance=binance_ratio,
            recommended_split_ratio_uniswap=uniswap_ratio,
        )

    if cost_diff_pct is not None and cost_diff_pct <= NEAR_TIE_THRESHOLD_PCT:
        template = TEMPLATES["near_tie"]
        return Explanation(
            decision_key="near_tie",
            title=template["title"],
            summary=template["summary"],
            details=[
                f"Venue difference: {cost_diff_pct:.4f}%.",
            ],
            warnings=_warning_list(),
            recommended_venue=venue or None,
        )

    if venue == "binance":
        dex_price_impact_pct = _safe_number(best_route.get("dex_price_impact_pct"), 0.0)
        cex_slippage_pct = _safe_number(best_route.get("cex_slippage_pct"), 0.0)

        if dex_price_impact_pct > LOW_IMPACT_THRESHOLD_PCT:
            template = TEMPLATES["cex_wins_dex_impact"]
            return Explanation(
                decision_key="cex_wins_dex_impact",
                title=template["title"],
                summary=template["summary"],
                details=[
                    f"Uniswap price impact: {dex_price_impact_pct:.4f}%.",
                    f"Binance slippage: {cex_slippage_pct:.4f}%.",
                ],
                warnings=_warning_list(),
                recommended_venue="binance",
            )

        template = TEMPLATES["cex_wins_both_low"]
        return Explanation(
            decision_key="cex_wins_both_low",
            title=template["title"],
            summary=template["summary"],
            details=[
                f"Uniswap price impact: {dex_price_impact_pct:.4f}%.",
                f"Binance slippage: {cex_slippage_pct:.4f}%.",
            ],
            warnings=_warning_list(),
            recommended_venue="binance",
        )

    template = TEMPLATES["dex_wins"]
    return Explanation(
        decision_key="dex_wins",
        title=template["title"],
        summary=template["summary"],
        details=[
            f"Selected venue: {venue or 'uniswap'}.",
        ],
        warnings=_warning_list(),
        recommended_venue=venue or "uniswap",
    )