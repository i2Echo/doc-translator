from __future__ import annotations

import re

from doc_translator.render_guards.font_router import normalize_language_code


THAI_TEXT_RE = re.compile(r"[\u0e00-\u0e7f]+")
ZERO_WIDTH_SPACE = "\u200b"


def apply_thai_word_wrap_shield(text: str, language: str | None) -> str:
    if normalize_language_code(language) != "th" or ZERO_WIDTH_SPACE in text:
        return text

    try:
        from pythainlp.tokenize import word_tokenize
    except ImportError:
        # A per-character fallback makes Thai layout worse by creating a break
        # opportunity between every glyph. If the segmenter is unavailable,
        # keep the text intact instead of degrading it.
        return text

    def shield(match: re.Match[str]) -> str:
        tokens = [token for token in word_tokenize(match.group(0), engine="newmm", keep_whitespace=False) if token]
        return ZERO_WIDTH_SPACE.join(tokens) if len(tokens) > 1 else match.group(0)

    return THAI_TEXT_RE.sub(shield, text)
