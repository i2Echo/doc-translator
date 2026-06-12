from __future__ import annotations

import re


BOLD_FONT_HINTS = ("bold", "black", "heavy", "demi", "semibold")
FONT_SUBSET_PREFIX_PATTERN = re.compile(r"^[A-Z]{6}\+")
FONT_CAMEL_CASE_BOUNDARY_PATTERN = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
FONT_SPLIT_PATTERN = re.compile(r"[^a-z0-9]+")
FONT_IGNORED_TOKENS = frozenset({"ttf", "ttc", "otf", "psmt"})


def tokenize_font_name(font_name: str) -> tuple[str, ...]:
    if not font_name:
        return ()
    expanded = FONT_SUBSET_PREFIX_PATTERN.sub("", str(font_name or ""))
    expanded = FONT_CAMEL_CASE_BOUNDARY_PATTERN.sub(" ", expanded)
    return tuple(
        token
        for token in FONT_SPLIT_PATTERN.split(expanded.casefold())
        if token and token not in FONT_IGNORED_TOKENS
    )


def font_name_has_hint(font_name: str, hints: tuple[str, ...]) -> bool:
    normalized_name = "".join(tokenize_font_name(font_name))
    return any(hint in normalized_name for hint in hints)


def detect_font_style(font_names: list[str]) -> str | None:
    return "BOLD" if any(font_name_has_hint(font_name, BOLD_FONT_HINTS) for font_name in font_names) else None
