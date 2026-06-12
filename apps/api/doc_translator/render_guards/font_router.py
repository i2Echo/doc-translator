from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


LANGUAGE_ALIASES = {
    "zh": "zh",
    "zh-cn": "zh",
    "chinese": "zh",
    "simplified chinese": "zh",
    "en": "en",
    "english": "en",
    "ja": "ja",
    "japanese": "ja",
    "ko": "ko",
    "korean": "ko",
    "ms": "ms",
    "malay": "ms",
    "th": "th",
    "thai": "th",
    "vi": "vi",
    "vietnamese": "vi",
}


@dataclass(frozen=True, slots=True)
class LanguageFontRoute:
    code: str
    regular: str | None
    bold: str | None
    scale: float


def normalize_language_code(language: str | None) -> str | None:
    return LANGUAGE_ALIASES.get(str(language or "").strip().casefold())


def _config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "languages_routing.json"


def _first_existing_path(candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


@lru_cache(maxsize=1)
def load_language_font_routes() -> dict[str, LanguageFontRoute]:
    payload = json.loads(_config_path().read_text(encoding="utf-8"))
    routes: dict[str, LanguageFontRoute] = {}
    for code, route in payload.items():
        routes[code] = LanguageFontRoute(
            code=code,
            regular=_first_existing_path(route.get("regular", ())),
            bold=_first_existing_path(route.get("bold", ())),
            scale=float(route.get("scale", 1.0) or 1.0),
        )
    return routes


def font_route_for_language(language: str | None) -> LanguageFontRoute | None:
    code = normalize_language_code(language)
    if code is None:
        return None
    return load_language_font_routes().get(code)
