from __future__ import annotations


def minimum_sibling_font_size(cells: list[dict[str, object]], fallback: float) -> float:
    sizes = [
        float(cell.get("font_size_current") or cell.get("font_size_original") or fallback)
        for cell in cells
        if isinstance(cell, dict)
    ]
    return min(sizes) if sizes else fallback
