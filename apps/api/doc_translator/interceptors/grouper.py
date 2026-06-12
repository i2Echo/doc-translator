from __future__ import annotations


def dominant_value(values: list[int]) -> int | None:
    if not values:
        return None
    return max(set(values), key=values.count)
