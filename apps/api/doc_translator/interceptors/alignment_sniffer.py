from __future__ import annotations


CENTER_ALIGNMENT_TOLERANCE = 5.0


def sniff_alignment(page_width: float, rect_mid_x: float, *, tolerance: float = CENTER_ALIGNMENT_TOLERANCE) -> str | None:
    if page_width <= 0:
        return None
    return "CENTER" if abs(rect_mid_x - page_width / 2) <= tolerance else None
