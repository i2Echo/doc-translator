from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


_NUMERIC_UNIT_TOKEN_RE = re.compile(r"^[+\-\u00b1]?(?:\d+(?:[.,]\d+)?|\.\d+)(?:[%\u00b0\u03a9\u03bc\u00b5A-Za-z/._:+-]+)?(?:\(\d+\))?$")
_COMPOSITE_UNIT_TOKEN_RE = re.compile(r"^[A-Za-z]+(?:/[\u00b0\u03a9\u03bc\u00b5A-Za-z]+)+$")
_TEMPERATURE_UNIT_TOKEN_RE = re.compile(r"^\u00b0[CF]$")
_SHORT_UPPER_TOKEN_RE = re.compile(r"^[A-Z]{2,4}$")
_TECHNICAL_UPPER_TOKEN_RE = re.compile(r"^[A-Z]{5,10}$")
_TECHNICAL_CAMEL_TOKEN_RE = re.compile(r"^[a-z]{1,2}[A-Z][A-Za-z0-9]*$")
_HEX_SUFFIX_TOKEN_RE = re.compile(r"^(?:0x)?[0-9A-Fa-f]+h$")
_MIXED_IDENTIFIER_TOKEN_RE = re.compile(r"^(?=.*(?:\d|[/._:+%#@&=\u00b0\u03a9\u03bc\u00b5()]))[A-Za-z0-9\u00b0\u03a9\u03bc\u00b5/._:+%#@&=\-()]+$")
_PURE_SYMBOL_TOKEN_RE = re.compile(r"^[^A-Za-z0-9\s]+$")
_GREEK_CHAR_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
_WRAPPING_PUNCTUATION = "[]{}<>,;:+-\u00b1"
_TECHNICAL_UPPER_SUBSTRINGS = frozenset(
    {
        "ADDR",
        "ALERT",
        "BUF",
        "CLK",
        "DAT",
        "DIFF",
        "DR",
        "FS",
        "GAIN",
        "GND",
        "GPIO",
        "HIGH",
        "IO",
        "LOW",
        "LSB",
        "MSB",
        "MUX",
        "OSC",
        "PGA",
        "RDY",
        "SCL",
        "SDA",
        "STA",
        "STO",
        "VDD",
        "VSS",
    }
)
_COMMON_UNIT_TOKENS = frozenset(
    {
        "a",
        "ma",
        "ua",
        "v",
        "mv",
        "uv",
        "w",
        "mw",
        "s",
        "ms",
        "us",
        "ns",
        "ps",
        "hz",
        "khz",
        "mhz",
        "ghz",
        "db",
        "dbm",
        "ppm",
        "ppb",
        "bit",
        "bits",
        "pt",
        "mm",
        "cm",
        "nm",
        "um",
        "kg",
        "mg",
        "kohm",
        "mohm",
        "ohm",
        "ω",
        "°c",
        "°f",
    }
)
_COMMON_ENUM_TOKENS = frozenset(
    {
        "yes",
        "no",
        "on",
        "off",
        "true",
        "false",
        "n/a",
        "na",
    }
)


@dataclass(frozen=True, slots=True)
class TranslationValidation:
    missing_keys: tuple[str, ...]
    untranslated_keys: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_keys and not self.untranslated_keys


def flatten_preview_text(preview: dict, *, source: bool) -> dict[str, str]:
    text_field = "src_text" if source else "tgt_text"
    flattened: dict[str, str] = {}
    for page in preview.get("pages", []):
        if not isinstance(page, dict):
            continue
        for block in page.get("blocks", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "table":
                for cell in block.get("cells", []):
                    if isinstance(cell, dict) and cell.get("cell_id"):
                        flattened[str(cell["cell_id"])] = str(cell.get(text_field, ""))
                continue
            if block.get("block_id"):
                flattened[str(block["block_id"])] = str(block.get(text_field, ""))
    return flattened


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or ""))).casefold()


def _is_preserved_token(token: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(token or "")).strip(_WRAPPING_PUNCTUATION).strip()
    collapsed = re.sub(r"\s+", "", normalized)
    if not collapsed:
        return True
    if len(collapsed) == 1:
        return True
    if collapsed.casefold() in _COMMON_UNIT_TOKENS:
        return True
    if collapsed.casefold() in _COMMON_ENUM_TOKENS:
        return True
    if _PURE_SYMBOL_TOKEN_RE.fullmatch(collapsed):
        return True
    if _NUMERIC_UNIT_TOKEN_RE.fullmatch(collapsed):
        return True
    if _TEMPERATURE_UNIT_TOKEN_RE.fullmatch(collapsed):
        return True
    if _COMPOSITE_UNIT_TOKEN_RE.fullmatch(collapsed):
        return True
    if _SHORT_UPPER_TOKEN_RE.fullmatch(collapsed):
        return True
    if _TECHNICAL_UPPER_TOKEN_RE.fullmatch(collapsed) and any(part in collapsed for part in _TECHNICAL_UPPER_SUBSTRINGS):
        return True
    if _TECHNICAL_CAMEL_TOKEN_RE.fullmatch(collapsed):
        return True
    if _HEX_SUFFIX_TOKEN_RE.fullmatch(collapsed):
        return True
    if _MIXED_IDENTIFIER_TOKEN_RE.fullmatch(collapsed):
        return True
    if _GREEK_CHAR_RE.search(collapsed):
        return True
    if not any(char.isalpha() for char in collapsed):
        return True
    return False


def _allows_identical_translation(text: str) -> bool:
    lines = [line.strip() for line in unicodedata.normalize("NFKC", str(text or "")).splitlines() if line.strip()]
    if not lines:
        return True
    for line in lines:
        tokens = [token for token in re.split(r"\s+", line) if token]
        if not tokens or not all(_is_preserved_token(token) for token in tokens):
            return False
    return True


def should_preserve_source_text(text: str) -> bool:
    return _allows_identical_translation(text)


def validate_translation_map(source_map: dict[str, str], translated_map: dict[str, str]) -> TranslationValidation:
    missing: list[str] = []
    untranslated: list[str] = []
    for key, source_text in source_map.items():
        translated_text = translated_map.get(key)
        if translated_text is None or (source_text.strip() and not str(translated_text).strip()):
            missing.append(key)
            continue
        if (
            source_text.strip()
            and _normalized_text(source_text) == _normalized_text(str(translated_text))
            and not _allows_identical_translation(source_text)
        ):
            untranslated.append(key)
    return TranslationValidation(tuple(missing), tuple(untranslated))
