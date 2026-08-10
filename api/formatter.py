def _fmt_num(value, decimals: int = 6) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_pct(value) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.4f}%"
    except (TypeError, ValueError):
        return "n/a"


def format_freshness_line(data: dict) -> str:
    now_ms = data.get("now_ms")
    binance_ts = data.get("binance_timestamp_ms")
    uniswap_ts = data.get("uniswap_timestamp_ms")

    if now_ms is None or binance_ts is None or uniswap_ts is None:
        return "Data freshness: n/a"

    try:
        binance_age_s = max(0.0, (int(now_ms) - int(binance_ts)) / 1000.0)
        uniswap_age_s = max(0.0, (int(now_ms) - int(uniswap_ts)) / 1000.0)
    except (TypeError, ValueError):
        return "Data freshness: n/a"

    return (
        f"Data freshness: Binance {binance_age_s:.1f}s ago, "
        f"Uniswap {uniswap_age_s:.1f}s ago"
    )


def format_split_block(split: dict) -> str:
    if not split or not split.get("is_valid"):
        return "Split analysis:\n  Not available"

    lines = [
        "Split analysis:",
        f"  Improves over single venue: {'yes' if split.get('improves_over_single') else 'no'}",
    ]

    binance_leg = split.get("binance_leg")
    if binance_leg:
        lines.append(
            f"  Binance allocation: {_fmt_pct(binance_leg.get('ratio', 0.0))} "
            f"of order, input {_fmt_num(binance_leg.get('input_amount'))}"
        )

    uniswap_leg = split.get("uniswap_leg")
    if uniswap_leg:
        lines.append(
            f"  Uniswap allocation: {_fmt_pct(uniswap_leg.get('ratio', 0.0))} "
            f"of order, input {_fmt_num(uniswap_leg.get('input_amount'))}"
        )

    if split.get("total_cost") is not None:
        lines.append(f"  Split total cost: {_fmt_num(split.get('total_cost'))}")

    if split.get("unit_cost") is not None:
        lines.append(f"  Split unit cost: {_fmt_num(split.get('unit_cost'))}")

    if split.get("net_proceeds") is not None:
        lines.append(f"  Split net proceeds: {_fmt_num(split.get('net_proceeds'))}")

    if split.get("effective_proceeds") is not None:
        lines.append(
            f"  Split effective proceeds: {_fmt_num(split.get('effective_proceeds'))}"
        )

    return "\n".join(lines)


def format_route_report(data: dict, explanation) -> str:
    best_route = data["best_route"]

    lines = [
        f"RouteFlow Quote — {data['symbol']} {data['side']} {data['input_amount']}",
        f"Recommendation: {explanation.title}",
    ]

    venue_label = best_route.get("venue") or "split"
    lines.append(f"Selected route: {venue_label}")

    if best_route.get("total_cost") is not None:
        lines.append(
            f"Best total cost: {_fmt_num(best_route.get('total_cost'))} "
            f"(unit cost {_fmt_num(best_route.get('unit_cost'))})"
        )

    if best_route.get("net_proceeds") is not None:
        lines.append(
            f"Best net proceeds: {_fmt_num(best_route.get('net_proceeds'))} "
            f"(effective proceeds {_fmt_num(best_route.get('effective_proceeds'))})"
        )

    lines.append("")
    lines.append(f"{explanation.title}: {explanation.summary}")

    for detail in explanation.details:
        lines.append(f"- {detail}")

    for warning in explanation.warnings:
        lines.append(f"! {warning}")

    lines.append("")
    lines.append("Venue comparison:")
    lines.append(
        f"- Binance: exec {_fmt_num(data['binance'].get('execution_price'))}, "
        f"slippage {_fmt_pct(data['binance'].get('slippage_pct'))}"
    )
    lines.append(
        f"- Uniswap: exec {_fmt_num(data['uniswap'].get('execution_price'))}, "
        f"slippage {_fmt_pct(data['uniswap'].get('slippage_pct'))}"
    )

    if data.get("split_evaluated"):
        lines.append("")
        lines.append(format_split_block(data.get("split")))

    lines.append("")
    lines.append(format_freshness_line(data))

    return "\n".join(lines)