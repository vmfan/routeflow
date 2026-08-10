from copy import deepcopy


def _level_price(level):
    return float(level[0])


def _level_volume(level):
    return float(level[1])


def depletebook(book, fill):
    residual = deepcopy(book)

    side = fill.get("side")
    remaining = float(fill.get("filled_size", 0.0))

    if remaining < 0.0:
        raise ValueError("filled_size must be non-negative.")

    if side not in {"buy", "sell"}:
        raise ValueError("fill side must be 'buy' or 'sell'.")

    levels_key = "asks" if side == "buy" else "bids"
    levels = residual.get(levels_key, [])
    new_levels = []

    for level in levels:
        price = _level_price(level)
        volume = _level_volume(level)

        if volume < 0.0:
            raise ValueError("book level volume must be non-negative.")

        if remaining <= 0.0:
            new_levels.append([price, volume])
            continue

        consumed = min(volume, remaining)
        leftover = volume - consumed
        remaining -= consumed

        if leftover > 1e-12:
            new_levels.append([price, leftover])

    residual[levels_key] = new_levels
    return residual


def evolvepool(pool, amountin: float, amountout: float):
    if amountin < 0.0 or amountout < 0.0:
        raise ValueError("amountin and amountout must be non-negative.")

    updated = deepcopy(pool)

    reserve_a = float(updated["reserve_token_a"])
    reserve_b = float(updated["reserve_token_b"])

    if reserve_a <= 0.0 or reserve_b <= 0.0:
        raise ValueError("pool reserves must be positive.")

    trade_direction = updated.get("trade_direction", "a_to_b")

    if trade_direction == "a_to_b":
        reserve_a += amountin
        reserve_b -= amountout
    elif trade_direction == "b_to_a":
        reserve_b += amountin
        reserve_a -= amountout
    else:
        raise ValueError("trade_direction must be 'a_to_b' or 'b_to_a'.")

    if reserve_a <= 0.0 or reserve_b <= 0.0:
        raise ValueError("pool evolution produced non-positive reserves.")

    updated["reserve_token_a"] = reserve_a
    updated["reserve_token_b"] = reserve_b
    return updated