from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_NUMERIC_OR_SYMBOL_RE = re.compile(r"^[^A-Za-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+$")
_PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?$", re.IGNORECASE)
_ROMAN_PAGE_RE = re.compile(r"^[ivxlcdm]{1,8}$", re.IGNORECASE)
_TECHNICAL_TOKEN_RE = re.compile(r"^(?=.*(?:\d|[/._:+%#@&=\-()]))[A-Za-z0-9/._:+%#@&=\-()]+$")
_SHORT_UPPER_TOKEN_RE = re.compile(r"^[A-Z]{2,6}$")
_DOT_LEADER_TOC_RE = re.compile(r"(?:\.|·|…|\s){4,}\d{1,4}\s*$")
_TOC_ENTRY_RE = re.compile(r"^(?P<title>.*?)(?P<leader>(?:[.\u00b7\u2026]|\s){4,})(?P<page>\d{1,4})\s*$")
_TRAILING_TOC_LOCATOR_RE = re.compile(r"(?:[.\u00b7\u2026]|\s)*\d{1,4}\s*$")
_NUMBERED_LINE_START_RE = re.compile(r"^\s*(?:\(\d{1,3}\)|\d{1,3}[.)])\s+")
_NUMBERED_MARKER_RE = re.compile(r"(?:\(\d{1,3}\)|\d{1,3}[.)])\s*")
_BABELDOC_STYLE_PLACEHOLDER_RE = re.compile(r"</?b\d+>", re.IGNORECASE)
_MARKETING_STATUS_LINE_RE = re.compile(r"^\s*(ACTIVE|LIFEBUY|NRND|PREVIEW|OBSOLETE)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_BABELDOC_INLINE_PLACEHOLDER_TOKEN = r"(?:\{[^{}\s]+\}|</?b\d+>)"
_PLACEHOLDER_TOKEN_RE = re.compile(r"\{[^{}\s]+\}")
_PROTECTED_TOKEN_PLACEHOLDER_RE = re.compile(r"\bDTX[A-F0-9]{10}Q\b", re.IGNORECASE)
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_TRAILING_UNIT_PARENS_RE = re.compile(r"[\(（]([^()（）]+)[\)）]\s*$")
_INLINE_PUNCTUATION_FRAGMENT_RE = re.compile(r"^[\.,:;/%+\-–±()]+$")
_AXIS_LABEL_CONNECTOR_WORDS = frozenset({"of", "and", "or", "vs", "per", "from", "to", "in", "on", "for", "with"})
_MEASUREMENT_UNIT_TOKEN = r"(?:mm|cm|m|nm|[µμ]m|um|in|mil)"
_TECHNICAL_RATIO_TOKEN_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?:LSB|ppm|ns|[µμ]s|us|ms|s|M(?:Ω|Ω)|k(?:Ω|Ω)|[ΩΩ]|[µμ]A|uA|mA|[µμ]V|uV|mV|V|°C|℃|dB|kHz|MHz|Hz|SPS|pF|nF|[µμ]F|uF|FSR|DIV|%)"
    r"(?:\s+of\s+FSR)?"
    r"(?:/(?:LSB|ppm|ns|[µμ]s|us|ms|s|M(?:Ω|Ω)|k(?:Ω|Ω)|[ΩΩ]|[µμ]A|uA|mA|[µμ]V|uV|mV|V|°C|℃|dB|kHz|MHz|Hz|SPS|pF|nF|[µμ]F|uF|FSR|DIV|%)"
    r"(?:\s+of\s+FSR)?)+"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)
_TECHNICAL_NUMBER_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+±]?(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*(?:M(?:Ω|Ω)|k(?:Ω|Ω)|[ΩΩ]|[µμ]A|uA|mA|nA|[µμ]V|uV|mV|V|ns|[µμ]s|us|ms|s|°C|℃|dB|kHz|MHz|Hz|SPS|mW|W|pF|nF|[µμ]F|uF|%|"
    + _MEASUREMENT_UNIT_TOKEN + r")"
    r"(?:/(?:LSB|ppm|ns|[µμ]s|us|ms|s|M(?:Ω|Ω)|k(?:Ω|Ω)|[ΩΩ]|[µμ]A|uA|mA|[µμ]V|uV|mV|V|°C|℃|dB|kHz|MHz|Hz|SPS|pF|nF|[µμ]F|uF|FSR|DIV|%))?"
    r"(?![A-Za-z])"
)
_DIMENSION_CHAIN_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[-+]?\d+(?:[.,]\d+)?\s*" + _MEASUREMENT_UNIT_TOKEN +
    r"(?:\s*[×xX*]\s*[-+]?\d+(?:[.,]\d+)?\s*" + _MEASUREMENT_UNIT_TOKEN + r")+"
    r"(?![A-Za-z])"
)
_PLACEHOLDER_BRIDGED_DIMENSION_CHAIN_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[-+]?\d+(?:[.,]\d+)?\s*" + _MEASUREMENT_UNIT_TOKEN +
    r"(?:\s*" + _BABELDOC_INLINE_PLACEHOLDER_TOKEN + r"+\s*(?:[-+]?\d+(?:[.,]\d+)?|[.,]\d+)\s*" + _MEASUREMENT_UNIT_TOKEN + r")+"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)
_TECHNICAL_UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?:M(?:Ω|Ω)|k(?:Ω|Ω)|[ΩΩ]|[µμ]A|uA|mA|nA|[µμ]V|uV|mV|V|ns|[µμ]s|us|ms|°C|℃|dB|kHz|MHz|Hz|SPS|mW|W|pF|nF|[µμ]F|uF|LSB|ppm|FSR|DIV|%)(?![A-Za-z])",
    re.IGNORECASE,
)
_AXIS_LABEL_TEXT_RE = re.compile(
    r"^[A-Za-z][A-Za-z\s/+&-]{1,70}\s*"
    r"\((?:M(?:Ω|Ω)|k(?:Ω|Ω)|[ΩΩ]|[µμ]A|uA|mA|[µμ]V|uV|mV|V|°C|℃|dB|kHz|MHz|Hz|SPS|mW|W|pF|nF|[µμ]F|uF|LSB|ppm|FSR|%)"
    r"(?:\s+of\s+FSR)?\)$"
)
_TECHNICAL_IDENTIFIER_RE = re.compile(
    r"\b(?:VDD|VSS|VCC|VREF|VIN|VOUT|VIH|VIL|VOH|VOL|GND|IOL|IOH|ISINK|IL|IH|TA|TJ|TS|TSTG|FCM|DR|PGA|ADC|I2C|UART|SCL|SDA|ADDR|TTL|TI|DIV|FS|LSB|PPM|LM\d+|ADS\d+|MSP430F\d+)\b",
    re.IGNORECASE,
)
_TECHNICAL_COMPOUND_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z]{2,}[A-Z0-9]*)(?:_(?:[A-Z]{2,}[A-Z0-9]*|\d+))+(?![A-Za-z0-9])"
)
_TECHNICAL_COMPACT_EQUATION_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"[A-Za-z][A-Za-z0-9_]{0,15}\s*=\s*[-+±]?\d+(?:[.,]\d+)?\s*"
    r"(?:M(?:Ω|Ω)|k(?:Ω|Ω)|[ΩΩ]|[µμ]A|uA|mA|nA|[µμ]V|uV|mV|V|ns|[µμ]s|us|ms|s|°C|℃|dB|kHz|MHz|Hz|SPS|mW|W|pF|nF|[µμ]F|uF|%|"
    + _MEASUREMENT_UNIT_TOKEN + r")"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_PLACEHOLDER_BRIDGED_TECHNICAL_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:[A-Z]{1,}[A-Z0-9]*|[A-Za-z]\d[A-Za-z])"
    r"(?:"
    + _BABELDOC_INLINE_PLACEHOLDER_TOKEN
    + r"(?:[A-Z]{1,}[A-Z0-9]*|\d+|[A-Za-z])"
    r")+"
    r"(?![A-Za-z0-9])"
)
_SINGLE_LETTER_TECHNICAL_RE = re.compile(r"(?<![A-Za-z])(?:R[ABC]?|C)(?![A-Za-z])")
_SPACE_COLLAPSE_RE = re.compile(r"\s+")
_CJK_AXIS_LABEL_FONT_SIZE = 8.0
_VERTICAL_AXIS_LABEL_TOP_PADDING_RATIO = 0.22
_VERTICAL_AXIS_LABEL_BOTTOM_PADDING_RATIO = 0.12
_VERTICAL_AXIS_LABEL_CJK_ADVANCE_RATIO = 1.08
_VERTICAL_AXIS_LABEL_LATIN_ADVANCE_RATIO = 0.74
_VERTICAL_AXIS_LABEL_PUNCT_ADVANCE_RATIO = 0.58
_VERTICAL_AXIS_LABEL_SPACE_ADVANCE_RATIO = 0.42
_VERTICAL_AXIS_LABEL_INTER_CHAR_GAP_RATIO = 0.08
_VERTICAL_AXIS_LABEL_CROSS_PADDING = 0.35
_TECHNICAL_UPPER_TOKENS = frozenset(
    {
        "ADC",
        "ADDR",
        "ALERT",
        "BUF",
        "CLK",
        "DAC",
        "DIFF",
        "GND",
        "GPIO",
        "I2C",
        "IO",
        "LSB",
        "MSB",
        "MUX",
        "OSC",
        "PGA",
        "RDY",
        "SCL",
        "SDA",
        "VDD",
        "VSS",
    }
)
_MARKETING_STATUS_TRANSLATIONS = {
    "ACTIVE": "活跃",
    "LIFEBUY": "终身购买",
    "NRND": "不推荐新设计",
    "PREVIEW": "预览",
    "OBSOLETE": "过时",
}
_SANS_FONT_NAME_HINTS = (
    "arial",
    "helvetica",
    "univers",
    "gotham",
    "avenir",
    "frutiger",
    "calibri",
    "verdana",
    "tahoma",
    "trebuchet",
    "sourcehansans",
    "notosans",
    "sans",
)
_SERIF_FONT_NAME_HINTS = (
    "times",
    "georgia",
    "garamond",
    "baskerville",
    "cambria",
    "constantia",
    "palatino",
    "bodoni",
    "minion",
    "sourcehanserif",
    "notoserif",
    "serif",
)


@dataclass(slots=True)
class ParagraphRole:
    paragraph_id: str
    page_number: int
    role: str
    policy: str
    confidence: float
    text: str
    rect: tuple[float, float, float, float] | None
    group_id: str | None = None
    evidence: tuple[str, ...] = ()


@dataclass(slots=True)
class _ParagraphRecord:
    paragraph_id: str
    object_id: int
    page_number: int
    page_index: int
    paragraph_index: int
    text: str
    canonical_text: str
    rect: tuple[float, float, float, float] | None
    page_rect: tuple[float, float, float, float] | None
    vertical: bool
    layout_label: str | None
    xobj_id: int | str | None
    role: str = "body"
    policy: str = "pass_through"
    confidence: float = 0.0
    group_id: str | None = None
    evidence: tuple[str, ...] = ()

    def to_role(self) -> ParagraphRole:
        return ParagraphRole(
            paragraph_id=self.paragraph_id,
            page_number=self.page_number,
            role=self.role,
            policy=self.policy,
            confidence=self.confidence,
            text=self.text,
            rect=self.rect,
            group_id=self.group_id,
            evidence=self.evidence,
        )


@dataclass(frozen=True, slots=True)
class _TranslationSnapshot:
    unicode: str
    composition: list[Any]


@dataclass(slots=True)
class BabeldocHookContext:
    working_dir: Path | None = None
    target_language: str | None = None
    records_by_id: dict[str, _ParagraphRecord] = field(default_factory=dict)
    records_by_object_id: dict[int, _ParagraphRecord] = field(default_factory=dict)
    paragraphs_by_id: dict[str, Any] = field(default_factory=dict)
    groups: dict[str, list[str]] = field(default_factory=dict)
    phase_events: list[dict[str, Any]] = field(default_factory=list)
    applied_events: list[dict[str, Any]] = field(default_factory=list)
    axis_diagnostics: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"paragraph_candidates": [], "character_groups": []}
    )
    _translations: dict[str, _TranslationSnapshot] = field(default_factory=dict)
    _source_layouts: dict[str, _TranslationSnapshot] = field(default_factory=dict)
    _protected_tokens: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    _toc_prefix_width_by_id: dict[str, int] = field(default_factory=dict)
    _axis_label_translation_cache: dict[str, str] = field(default_factory=dict)
    _marketing_status_labels: dict[str, str] = field(default_factory=dict)
    _before_structure_snapshot: dict[str, Any] | None = None
    _after_structure_snapshot: dict[str, Any] | None = None
    _fallback_line_protected_bands: set[str] = field(default_factory=set)
    _postprocess_focus_paragraph_ids: set[int] = field(default_factory=set)
    _definition_style_restored_paragraph_ids: set[int] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _reconciled: bool = False

    def set_working_dir(self, working_dir: Path) -> None:
        self.working_dir = working_dir

    def set_target_language(self, target_language: str) -> None:
        self.target_language = target_language

    def note_phase(self, phase: str, details: dict[str, Any] | None = None) -> None:
        self.phase_events.append(
            {
                "phase": phase,
                "at": datetime.now(timezone.utc).isoformat(),
                "details": details or {},
            }
        )

    def _focus_postprocess_paragraph(self, paragraph: Any) -> None:
        self._postprocess_focus_paragraph_ids.add(id(paragraph))

    def _needs_scoped_postprocess(self, paragraph: Any) -> bool:
        return id(paragraph) in self._postprocess_focus_paragraph_ids

    def classify_document(self, document: Any) -> None:
        records = self._collect_records(document)
        self.records_by_id = {record.paragraph_id: record for record in records}
        self.records_by_object_id = {record.object_id: record for record in records}
        self._fallback_line_protected_bands = _detect_fallback_line_underscore_bands(records)
        vertical_fragment_ids = _detect_vertical_label_fragment_ids(records)

        for record in records:
            if _is_toc_candidate(record, len(getattr(document, "page", []) or [])):
                _mark(record, "toc_entry", "translate_title_preserve_locator", 0.9, ("dot leader with trailing page number",))
                continue
            if record.paragraph_id in vertical_fragment_ids or _is_vertical_candidate(record):
                _mark(record, "vertical_label", "preserve", 0.9, ("vertical or high-narrow paragraph",))
                continue
            if record.paragraph_id in self._fallback_line_protected_bands:
                _mark(record, "preserved_token", "preserve", 0.98, ("fallback line underscore technical band",))
                continue
            if _is_preserve_candidate(record):
                _mark(record, "preserved_token", "preserve", 0.97, ("short stable token",))

        self._capture_source_layouts(records)
        self.axis_diagnostics["paragraph_candidates"] = _axis_paragraph_diagnostics(records)
        self._build_toc_alignment(records)
        self._classify_repeated_edge_text(records)
        self.note_phase(
            "classify_document",
            {
                "paragraphs": len(records),
                "roles": self._role_counts(),
                "groups": len(self.groups),
            },
        )
        self._before_structure_snapshot = self._build_structure_snapshot(document, stage="before_translation")

    def should_skip_translation(self, paragraph: Any) -> bool:
        record = self._record_for_paragraph(paragraph)
        text = str(getattr(paragraph, "unicode", "") or "")
        if record is not None and record.policy == "preserve":
            self.applied_events.append(
                {
                    "action": "skip_translation",
                    "paragraph_id": record.paragraph_id,
                    "role": record.role,
                    "policy": record.policy,
                }
            )
            return True
        if not _should_preserve_dynamic_text(text):
            return False
        if record is not None:
            _mark(record, "dynamic_preserve", "preserve", 0.84, ("short numeric/unit axis fragment",))
        self.applied_events.append(
            {
                "action": "skip_translation",
                "paragraph_id": record.paragraph_id if record is not None else None,
                "role": record.role if record is not None else "dynamic_preserve",
                "policy": "preserve",
            }
        )
        return True

    def translation_text_override(self, paragraph: Any, text: str, translate_input: Any | None = None) -> str:
        record = self._record_for_paragraph(paragraph)
        if record is None:
            return text
        if record.layout_label == "fallback_line" and record.text:
            text = record.text
        elif record.text:
            text = _normalize_translation_input_text(paragraph, record.text, text, translate_input, self.applied_events, record)
        marketing_status = _split_marketing_status_line(record.text or text)
        if marketing_status is not None:
            label, body = marketing_status
            self._marketing_status_labels[record.paragraph_id] = label
            text = body
        if record.role != "toc_entry":
            protected_text = self._protect_technical_tokens(record, text)
            return protected_text
        toc_parts = _split_toc_entry(text) or _split_toc_entry(record.text)
        if toc_parts is None:
            return text
        self.applied_events.append(
            {
                "action": "translate_toc_title_only",
                "paragraph_id": record.paragraph_id,
                "role": record.role,
                "policy": record.policy,
            }
        )
        return _normalize_toc_title(toc_parts[0])

    def translated_text_override(self, paragraph: Any, translate_input: Any, translated_text: str) -> str:
        source_text = str(getattr(translate_input, "unicode", "") or "")
        record = self._record_for_paragraph(paragraph)
        if record is not None and record.role == "toc_entry":
            toc_parts = _split_toc_entry(source_text) or _split_toc_entry(record.text)
            if toc_parts is None:
                return translated_text
            title, leader, page_number = toc_parts
            translated_title = _clean_toc_title_translation(translated_text, title)
            return _compose_toc_entry(title, leader, translated_title, page_number, self._toc_prefix_width_by_id.get(record.paragraph_id))
        if record is not None:
            translated_text = self._restore_protected_tokens(record, translated_text)
            translated_text = self._restore_neighbor_protected_placeholders(record, translated_text)
            if _has_inline_numbered_markers(record.text):
                translated_text = _strip_babeldoc_style_placeholders(translated_text)
            marketing_label = self._marketing_status_labels.get(record.paragraph_id)
            if marketing_label is not None:
                translated_text = f"{marketing_label}：{translated_text.strip()}"
        restored_text = _restore_source_line_breaks(source_text, translated_text)
        if restored_text != translated_text and record is not None:
            self.applied_events.append(
                {
                    "action": "restore_source_line_breaks",
                    "paragraph_id": record.paragraph_id,
                    "role": record.role,
                    "policy": record.policy,
                }
            )
        return restored_text

    def _protect_technical_tokens(self, record: _ParagraphRecord, text: str) -> str:
        protected_text, protected = _protect_technical_tokens_in_text(text)
        if not protected:
            return text
        self._protected_tokens[record.paragraph_id] = protected
        self.applied_events.append(
            {
                "action": "protect_technical_tokens",
                "paragraph_id": record.paragraph_id,
                "role": record.role,
                "count": len(protected),
            }
        )
        return protected_text

    def normalize_font_traits(self, document: Any) -> None:
        updated = 0
        samples: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            for font in getattr(page, "pdf_font", []) or []:
                updated += _normalize_pdf_font_traits(font, samples)
            for xobj in getattr(page, "pdf_xobject", []) or []:
                for font in getattr(xobj, "pdf_font", []) or []:
                    updated += _normalize_pdf_font_traits(font, samples)
        if updated:
            self.applied_events.append(
                {
                    "action": "normalize_pdf_font_traits",
                    "fonts": updated,
                    "samples": samples[:8],
                }
            )

    def _restore_protected_tokens(self, record: _ParagraphRecord, translated_text: str) -> str:
        protected = self._protected_tokens.get(record.paragraph_id)
        if not protected:
            return translated_text
        return _restore_protected_token_pairs(protected, translated_text)

    def _restore_neighbor_protected_placeholders(self, record: _ParagraphRecord, translated_text: str) -> str:
        unresolved = list(dict.fromkeys(_PROTECTED_TOKEN_PLACEHOLDER_RE.findall(str(translated_text or ""))))
        if not unresolved:
            return translated_text
        own_placeholders = {placeholder for placeholder, _token in self._protected_tokens.get(record.paragraph_id, [])}
        unresolved = [placeholder for placeholder in unresolved if placeholder not in own_placeholders]
        if not unresolved or record.page_number is None or record.paragraph_index is None:
            return translated_text

        candidate_records = sorted(
            (
                other
                for other in self.records_by_id.values()
                if other.page_number == record.page_number
                and other.paragraph_index is not None
                and other.paragraph_id != record.paragraph_id
                and abs(other.paragraph_index - record.paragraph_index) <= 2
            ),
            key=lambda other: (abs(other.paragraph_index - record.paragraph_index), other.paragraph_index),
        )
        if not candidate_records:
            return translated_text

        resolved = translated_text
        restored_pairs: list[tuple[str, str]] = []
        for placeholder in unresolved:
            replacement = None
            for candidate in candidate_records:
                for candidate_placeholder, candidate_token in self._protected_tokens.get(candidate.paragraph_id, []):
                    if candidate_placeholder.lower() != placeholder.lower():
                        continue
                    replacement = candidate_token
                    break
                if replacement is not None:
                    break
            if replacement is None:
                continue
            resolved = re.sub(re.escape(placeholder), replacement, resolved, flags=re.IGNORECASE)
            restored_pairs.append((placeholder, replacement))

        if restored_pairs:
            self.applied_events.append(
                {
                    "action": "restore_neighbor_protected_placeholders",
                    "paragraph_id": record.paragraph_id,
                    "page_number": record.page_number,
                    "restored": restored_pairs,
                }
            )
        return resolved

    def record_translation(self, paragraph: Any) -> None:
        record = self._record_for_paragraph(paragraph)
        if record is None:
            return
        composition = getattr(paragraph, "pdf_paragraph_composition", None) or []
        if not _is_copyable_unicode_composition(composition):
            return
        unicode_text = str(getattr(paragraph, "unicode", "") or "")
        with self._lock:
            self._translations[record.paragraph_id] = _TranslationSnapshot(
                unicode=unicode_text,
                composition=copy.deepcopy(composition),
            )

    def restore_definition_line_styles_after_translation(
        self,
        paragraph: Any,
        translated_text: str,
        source_composition: list[Any],
    ) -> bool:
        record = self._record_for_paragraph(paragraph)
        if record is None:
            return False
        if not self._needs_scoped_postprocess(paragraph):
            return False
        if _BABELDOC_STYLE_PLACEHOLDER_RE.search(str(translated_text or "")):
            return False
        restored = _restore_definition_line_styles_from_source(paragraph, source_composition)
        if not restored:
            return False
        self._definition_style_restored_paragraph_ids.add(id(paragraph))
        self.applied_events.append(
            {
                "action": "restore_definition_line_styles_after_translation",
                "paragraph_id": record.paragraph_id,
                "role": record.role,
                "layout_label": record.layout_label,
                "text": str(getattr(paragraph, "unicode", "") or "")[:180],
            }
        )
        return True

    def restore_source_layouts_before_typesetting(self, document: Any) -> None:
        restored = 0
        for page in getattr(document, "page", []) or []:
            for paragraph in getattr(page, "pdf_paragraph", []) or []:
                record = self._record_for_paragraph(paragraph)
                if record is None or record.role != "vertical_label":
                    continue
                snapshot = self._source_layouts.get(record.paragraph_id)
                if snapshot is None:
                    continue
                paragraph.unicode = snapshot.unicode
                paragraph.pdf_paragraph_composition = copy.deepcopy(snapshot.composition)
                paragraph.optimal_scale = 1.0
                restored += 1
        if restored:
            self.applied_events.append(
                {
                    "action": "restore_vertical_passthrough_layout",
                    "count": restored,
                }
            )

    def _should_skip_page_level_axis_group(
        self,
        page_number: int | None,
        group: list[Any],
        source_text: str,
    ) -> bool:
        if page_number is None:
            return False
        if _looks_like_table_column_group(group):
            return True
        page_records = [
            record
            for record in self.records_by_id.values()
            if record.page_number == page_number and record.rect is not None
        ]
        if not page_records:
            return False
        source_rect = _char_group_rect(group)

        matched_non_axis_records: set[str] = set()
        matched_axis_records: set[str] = set()
        matched_chars = 0
        for char in group:
            char_rect = _box_rect(getattr(char, "box", None))
            if char_rect is None:
                continue
            best_record = None
            best_overlap = 0.0
            for record in page_records:
                overlap = _rect_overlap_ratio(char_rect, record.rect)
                if overlap <= best_overlap:
                    continue
                best_overlap = overlap
                best_record = record
            if best_record is None or best_overlap < 0.55:
                fallback_record = _best_point_aligned_record(char_rect, page_records)
                if fallback_record is not None:
                    best_record = fallback_record
                    best_overlap = 0.55
            if best_record is None or best_overlap < 0.55:
                continue
            matched_chars += 1
            if (
                best_record.role == "vertical_label"
                or _looks_like_axis_label_fragment(best_record.text)
                or _looks_like_horizontal_axis_label(best_record.text)
            ):
                matched_axis_records.add(best_record.paragraph_id)
                continue
            matched_non_axis_records.add(best_record.paragraph_id)

        if matched_axis_records:
            return False
        if source_rect is not None and _looks_like_record_aligned_table_column(source_rect, page_records):
            return True
        if _looks_like_repeated_short_record_column(source_rect, page_records):
            return True
        if source_rect is not None and _group_overlaps_preserved_short_records(source_rect, page_records):
            return True
        if _is_strong_axis_label_source_text(source_text):
            return False
        if len(matched_non_axis_records) >= 3:
            return True
        return matched_chars >= 4 and len(matched_non_axis_records) >= 2

    def collapse_overlapping_same_baseline_fragments_before_translation(self, document: Any) -> bool:
        collapsed = 0
        samples = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 3:
                continue
            groups = _group_overlapping_same_baseline_paragraphs(paragraphs)
            if not groups:
                continue
            removed_indices: set[int] = set()
            for group in groups:
                live_group = [(index, paragraphs[index]) for index in group if index not in removed_indices]
                if not _looks_like_overlapping_fragment_cluster(live_group):
                    continue
                ordered_group = sorted(
                    live_group,
                    key=lambda item: (_box_rect(getattr(item[1], "box", None)) or (math.inf, math.inf, math.inf, math.inf))[0],
                )
                base_index, base = _overlapping_fragment_anchor(ordered_group)
                before_texts = [str(getattr(paragraph, "unicode", "") or "")[:80] for _index, paragraph in ordered_group]
                merged_text = ""
                merged_rect = None
                merged_composition = []
                absorbed_indices: list[int] = []
                for candidate_index, candidate in ordered_group:
                    candidate_rect = _box_rect(getattr(candidate, "box", None))
                    if candidate_rect is None:
                        continue
                    if merged_rect is None:
                        merged_text = str(getattr(candidate, "unicode", "") or "")
                        merged_rect = candidate_rect
                        merged_composition = list(getattr(candidate, "pdf_paragraph_composition", []) or [])
                        absorbed_indices.append(candidate_index)
                        continue
                    if not _should_absorb_overlapping_rect_fragment(merged_rect, candidate_rect):
                        continue
                    merged_text = _merged_text_with_overlap(
                        merged_text,
                        str(getattr(candidate, "unicode", "") or ""),
                        merged_rect,
                        candidate_rect,
                    )
                    merged_rect = _rect_union([merged_rect, candidate_rect]) or merged_rect
                    merged_composition.extend(list(getattr(candidate, "pdf_paragraph_composition", []) or []))
                    absorbed_indices.append(candidate_index)
                if len(absorbed_indices) < 3 or merged_rect is None:
                    continue
                base.unicode = merged_text
                _set_box_rect(getattr(base, "box", None), merged_rect)
                _set_plain_unicode_paragraph_text(base, merged_text)
                base.optimal_scale = None
                self._focus_postprocess_paragraph(base)
                for candidate_index in absorbed_indices:
                    if candidate_index == base_index:
                        continue
                    removed_indices.add(candidate_index)
                    collapsed += 1
                if len(samples) < 8 and any(index in removed_indices for index, _paragraph in ordered_group if index != base_index):
                    samples.append(
                        {
                            "before": before_texts,
                            "after": str(getattr(base, "unicode", "") or "")[:160],
                            "rect": _box_rect(getattr(base, "box", None)),
                        }
                    )
            if removed_indices:
                page.pdf_paragraph = [
                    paragraph
                    for paragraph_index, paragraph in enumerate(paragraphs)
                    if paragraph_index not in removed_indices
                ]
        if collapsed:
            self.applied_events.append(
                {
                    "action": "collapse_overlapping_same_baseline_fragments_before_translation",
                    "pairs": collapsed,
                    "samples": samples,
                }
            )
        return collapsed > 0

    def normalize_fragmented_paragraphs_before_translation(self, document: Any) -> bool:
        split_lines = 0
        split_samples = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if not paragraphs:
                continue
            rewritten = []
            for paragraph in paragraphs:
                if not _supports_visual_line_split(paragraph):
                    rewritten.append(paragraph)
                    continue
                parts = _split_paragraph_by_visual_lines(paragraph)
                rewritten.extend(parts)
                if len(parts) <= 1:
                    continue
                for part in parts:
                    self._focus_postprocess_paragraph(part)
                split_lines += len(parts) - 1
                if len(split_samples) < 8:
                    split_samples.append(
                        {
                            "source": str(getattr(paragraph, "unicode", "") or "")[:120],
                            "parts": [str(getattr(part, "unicode", "") or "")[:80] for part in parts],
                        }
                    )
            page.pdf_paragraph = rewritten
        if split_lines:
            self.applied_events.append(
                {
                    "action": "split_multiline_paragraphs_before_translation",
                    "paragraphs": split_lines,
                    "samples": split_samples,
                }
            )
        return split_lines > 0

    def remove_subsumed_same_line_duplicates_before_translation(self, document: Any) -> bool:
        removed = 0
        samples = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 2:
                continue
            removed_indices: set[int] = set()
            for candidate_index, candidate in enumerate(paragraphs):
                if candidate_index in removed_indices:
                    continue
                anchor_index = _find_subsuming_same_line_anchor(paragraphs, candidate_index, removed_indices)
                if anchor_index is None:
                    continue
                removed_indices.add(candidate_index)
                self._focus_postprocess_paragraph(paragraphs[anchor_index])
                removed += 1
                if len(samples) < 8:
                    samples.append(
                        {
                            "anchor": str(getattr(paragraphs[anchor_index], "unicode", "") or "")[:120],
                            "duplicate": str(getattr(candidate, "unicode", "") or "")[:120],
                            "rect": _box_rect(getattr(candidate, "box", None)),
                        }
                    )
            if removed_indices:
                page.pdf_paragraph = [
                    paragraph
                    for paragraph_index, paragraph in enumerate(paragraphs)
                    if paragraph_index not in removed_indices
                ]
        if removed:
            self.applied_events.append(
                {
                    "action": "remove_subsumed_same_line_duplicates_before_translation",
                    "paragraphs": removed,
                    "samples": samples,
                }
            )
        return removed > 0

    def split_fallback_line_technical_token_runs_before_translation(self, document: Any) -> bool:
        split_runs = 0
        samples = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 3:
                continue
            rewritten: list[Any] = []
            for index, paragraph in enumerate(paragraphs):
                token_parts = _fallback_line_split_tokens_with_underscore_context(paragraph, paragraphs, index)
                if len(token_parts) <= 1:
                    rewritten.append(paragraph)
                    continue
                rewritten.extend(token_parts)
                split_runs += 1
                if len(samples) < 10:
                    samples.append(
                        {
                            "source": str(getattr(paragraph, "unicode", "") or "")[:80],
                            "parts": [str(getattr(part, "unicode", "") or "")[:40] for part in token_parts],
                            "rect": _box_rect(getattr(paragraph, "box", None)),
                        }
                    )
            page.pdf_paragraph = rewritten
        if split_runs:
            self.applied_events.append(
                {
                    "action": "split_fallback_line_technical_token_runs_before_translation",
                    "paragraphs": split_runs,
                    "samples": samples,
                }
            )
        return split_runs > 0

    def merge_fallback_line_underscore_compounds_before_translation(self, document: Any) -> bool:
        merged = 0
        samples = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 3:
                continue
            ordered_items = [(paragraph, original_index) for original_index, paragraph in enumerate(paragraphs)]
            ordered_items.sort(key=lambda item: _paragraph_visual_sort_key(item[0], item[1]))
            removed_indices: set[int] = set()
            for index in range(len(ordered_items) - 2):
                if any(candidate_index in removed_indices for candidate_index in range(index, index + 3)):
                    continue
                left, left_original = ordered_items[index]
                middle, middle_original = ordered_items[index + 1]
                right, right_original = ordered_items[index + 2]
                if not _can_merge_fallback_line_underscore_compound(left, middle, right):
                    continue
                _merge_paragraphs(left, middle, separator="")
                _merge_paragraphs(left, right, separator="")
                removed_indices.update({middle_original, right_original})
                merged += 1
                if len(samples) < 12:
                    samples.append(
                        {
                            "parts": [
                                str(getattr(left, "unicode", "") or "")[:32],
                                str(getattr(middle, "unicode", "") or "")[:8],
                                str(getattr(right, "unicode", "") or "")[:32],
                            ],
                            "merged": str(getattr(left, "unicode", "") or "")[:64],
                            "rect": _box_rect(getattr(left, "box", None)),
                        }
                    )
            if removed_indices:
                page.pdf_paragraph = [
                    paragraph
                    for paragraph_index, paragraph in enumerate(paragraphs)
                    if paragraph_index not in removed_indices
                ]
        if merged:
            self.applied_events.append(
                {
                    "action": "merge_fallback_line_underscore_compounds_before_translation",
                    "pairs": merged,
                    "samples": samples,
                }
            )
        return merged > 0

    def normalize_fallback_line_texts_before_translation(self, document: Any) -> bool:
        normalized = 0
        samples = []
        for page in getattr(document, "page", []) or []:
            for paragraph in getattr(page, "pdf_paragraph", []) or []:
                if getattr(paragraph, "layout_label", None) != "fallback_line":
                    continue
                rebuilt = _rebuild_fallback_line_text(paragraph)
                if rebuilt is None:
                    continue
                original = str(getattr(paragraph, "unicode", "") or "")
                if not rebuilt.strip() or rebuilt == original:
                    continue
                paragraph.unicode = rebuilt
                normalized += 1
                if len(samples) < 10:
                    samples.append(
                        {
                            "before": original[:120],
                            "after": rebuilt[:120],
                            "rect": _box_rect(getattr(paragraph, "box", None)),
                        }
                    )
        if normalized:
            self.applied_events.append(
                {
                    "action": "normalize_fallback_line_texts_before_translation",
                    "paragraphs": normalized,
                    "samples": samples,
                }
            )
        return normalized > 0

    def merge_fallback_line_fragments_before_translation(self, document: Any) -> bool:
        merged = 0
        samples = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 2:
                continue
            removed_indices: set[int] = set()
            for index, fragment in enumerate(paragraphs):
                if index in removed_indices or not _is_small_fallback_line_fragment(fragment):
                    continue
                best_target_index = None
                best_score = None
                for target_index, target in enumerate(paragraphs):
                    if target_index == index or target_index in removed_indices:
                        continue
                    score = _fallback_line_fragment_attachment_score(fragment, target)
                    if score is None or (best_score is not None and score >= best_score):
                        continue
                    best_target_index = target_index
                    best_score = score
                if best_target_index is None:
                    continue
                _merge_paragraphs(paragraphs[best_target_index], fragment, separator="")
                removed_indices.add(index)
                merged += 1
                if len(samples) < 10:
                    samples.append(
                        {
                            "fragment": str(getattr(fragment, "unicode", "") or "")[:40],
                            "target": str(getattr(paragraphs[best_target_index], "unicode", "") or "")[:80],
                            "fragment_rect": _box_rect(getattr(fragment, "box", None)),
                            "target_rect": _box_rect(getattr(paragraphs[best_target_index], "box", None)),
                        }
                    )
            if removed_indices:
                page.pdf_paragraph = [
                    paragraph
                    for paragraph_index, paragraph in enumerate(paragraphs)
                    if paragraph_index not in removed_indices
                ]
        if merged:
            self.applied_events.append(
                {
                    "action": "merge_fallback_line_fragments_before_translation",
                    "pairs": merged,
                    "samples": samples,
                }
            )
        return merged > 0

    def merge_same_line_fragments_before_translation(self, document: Any) -> bool:
        merged = 0
        samples = []
        rejected_samples = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 2:
                continue
            ordered_items = [
                (paragraph, original_index)
                for original_index, paragraph in enumerate(paragraphs)
            ]
            ordered_items.sort(key=lambda item: _paragraph_visual_sort_key(item[0], item[1]))
            rewritten: list[tuple[int, Any]] = []
            consumed_indices: set[int] = set()
            index = 0
            while index < len(ordered_items):
                if index in consumed_indices:
                    index += 1
                    continue
                current, current_original_index = ordered_items[index]
                merged_original_indices = [current_original_index]
                while True:
                    candidate_index = self._best_same_line_fragment_candidate(
                        current,
                        index,
                        ordered_items,
                        consumed_indices,
                    )
                    if candidate_index is None:
                        candidate_index = self._best_wrapped_decimal_continuation_candidate(
                            current,
                            index,
                            ordered_items,
                            consumed_indices,
                        )
                    if candidate_index is None:
                        next_index = index + 1
                        while next_index < len(ordered_items) and next_index in consumed_indices:
                            next_index += 1
                        if next_index < len(ordered_items):
                            right, _right_original_index = ordered_items[next_index]
                            should_merge, reason = self._should_merge_same_line_fragments(current, right)
                            if (
                                not should_merge
                                and len(rejected_samples) < 12
                                and _looks_like_potential_same_line_fragment_pair(current, right)
                            ):
                                rejected_samples.append(
                                    {
                                        "left": str(getattr(current, "unicode", "") or "")[:120],
                                        "right": str(getattr(right, "unicode", "") or "")[:120],
                                        "left_rect": _box_rect(getattr(current, "box", None)),
                                        "right_rect": _box_rect(getattr(right, "box", None)),
                                        "reason": reason,
                                    }
                                )
                        break
                    right, right_original_index = ordered_items[candidate_index]
                    if self._should_attach_inline_punctuation_fragment(current, right):
                        if len(samples) < 8:
                            samples.append(
                                {
                                    "left": str(getattr(current, "unicode", "") or "")[:80],
                                    "right": str(getattr(right, "unicode", "") or "")[:80],
                                    "rect": _box_rect(getattr(current, "box", None)),
                                }
                            )
                        _merge_paragraphs(current, right, separator="")
                        self._focus_postprocess_paragraph(current)
                        merged_original_indices.append(right_original_index)
                        consumed_indices.add(candidate_index)
                        merged += 1
                        continue
                    should_merge, reason = self._should_merge_same_line_fragments(current, right)
                    if should_merge:
                        if len(samples) < 8:
                            samples.append(
                                {
                                    "left": str(getattr(current, "unicode", "") or "")[:80],
                                    "right": str(getattr(right, "unicode", "") or "")[:80],
                                    "rect": _box_rect(getattr(current, "box", None)),
                                }
                            )
                        _merge_paragraphs(current, right)
                    else:
                        if len(samples) < 8:
                            samples.append(
                                {
                                    "left": str(getattr(current, "unicode", "") or "")[:80],
                                    "right": str(getattr(right, "unicode", "") or "")[:80],
                                    "rect": _box_rect(getattr(current, "box", None)),
                                }
                            )
                        _merge_paragraphs(current, right, separator="")
                    self._focus_postprocess_paragraph(current)
                    merged_original_indices.append(right_original_index)
                    consumed_indices.add(candidate_index)
                    merged += 1
                rewritten.append((min(merged_original_indices), current))
                index += 1
            rewritten.sort(key=lambda item: item[0])
            page.pdf_paragraph = [paragraph for _original_index, paragraph in rewritten]

        if merged:
            self.applied_events.append(
                {
                    "action": "merge_same_line_fragments_before_translation",
                    "pairs": merged,
                    "samples": samples,
                }
            )
        if rejected_samples:
            self.applied_events.append(
                {
                    "action": "reject_same_line_fragment_merge",
                    "samples": rejected_samples,
                }
            )
        return merged > 0

    def _should_attach_inline_punctuation_fragment(self, left: Any, right: Any) -> bool:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        if left_record is not None and left_record.role in {"toc_entry", "vertical_label", "running_edge_text"}:
            return False
        if right_record is not None and right_record.role in {"toc_entry", "vertical_label", "running_edge_text"}:
            return False
        if (left_record is not None and _is_edge_band(left_record)) or (
            right_record is not None and _is_edge_band(right_record)
        ):
            return False
        if getattr(left, "xobj_id", None) != getattr(right, "xobj_id", None):
            return False
        right_text = str(getattr(right, "unicode", "") or "").strip()
        if not _is_inline_punctuation_fragment(right_text):
            return False
        left_rect = _box_rect(getattr(left, "box", None))
        right_rect = _box_rect(getattr(right, "box", None))
        if left_rect is None or right_rect is None:
            return False
        baseline_ok, _reason = _same_baseline_close_gap(left_rect, right_rect)
        return baseline_ok

    def _should_merge_same_line_fragments(self, left: Any, right: Any) -> tuple[bool, str]:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        if left_record is not None and left_record.role in {"toc_entry", "vertical_label", "running_edge_text"}:
            return False, f"left_role:{left_record.role}"
        if right_record is not None and right_record.role in {"toc_entry", "vertical_label", "running_edge_text"}:
            return False, f"right_role:{right_record.role}"
        if (left_record is not None and _is_edge_band(left_record)) or (
            right_record is not None and _is_edge_band(right_record)
        ):
            return False, "edge_band"
        if getattr(left, "xobj_id", None) != getattr(right, "xobj_id", None):
            return False, "different_xobj"

        left_text = str(getattr(left, "unicode", "") or "")
        right_text = str(getattr(right, "unicode", "") or "")
        if not _looks_like_mergeable_line_fragment(left_text, right_text):
            return False, "text_not_mergeable"

        left_rect = _box_rect(getattr(left, "box", None))
        right_rect = _box_rect(getattr(right, "box", None))
        if left_rect is None or right_rect is None:
            return False, "missing_rect"
        baseline_ok, reason = _same_baseline_close_gap(left_rect, right_rect)
        if not baseline_ok:
            return False, reason
        return True, "ok"

    def _best_same_line_fragment_candidate(
        self,
        current: Any,
        current_index: int,
        ordered_items: list[tuple[Any, int]],
        consumed_indices: set[int],
    ) -> int | None:
        current_rect = _box_rect(getattr(current, "box", None))
        if current_rect is None:
            return None
        best: tuple[tuple[float, float, float], int] | None = None
        for candidate_index, (candidate, _candidate_original_index) in enumerate(ordered_items):
            if candidate_index == current_index or candidate_index in consumed_indices:
                continue
            candidate_rect = _box_rect(getattr(candidate, "box", None))
            if candidate_rect is None:
                continue
            if candidate_rect[0] < current_rect[0]:
                continue
            if self._should_attach_inline_punctuation_fragment(current, candidate):
                gap = max(candidate_rect[0] - current_rect[2], -1.0)
                score = (0.0, gap, candidate_rect[0])
            else:
                should_merge, _reason = self._should_merge_same_line_fragments(current, candidate)
                if not should_merge:
                    continue
                gap = max(candidate_rect[0] - current_rect[2], -1.0)
                score = (1.0, gap, candidate_rect[0])
            if best is None or score < best[0]:
                best = (score, candidate_index)
        return None if best is None else best[1]

    def _best_wrapped_decimal_continuation_candidate(
        self,
        current: Any,
        current_index: int,
        ordered_items: list[tuple[Any, int]],
        consumed_indices: set[int],
    ) -> int | None:
        best: tuple[tuple[float, float], int] | None = None
        for candidate_index, (candidate, _candidate_original_index) in enumerate(ordered_items):
            if candidate_index == current_index or candidate_index in consumed_indices:
                continue
            score = _wrapped_decimal_continuation_score(current, candidate)
            if score is None:
                continue
            if best is None or score < best[0]:
                best = (score, candidate_index)
        return None if best is None else best[1]

    def split_numbered_lists_before_typesetting(self, document: Any) -> None:
        split_count = 0
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if not paragraphs:
                continue
            rewritten = []
            for paragraph in paragraphs:
                record = self._record_for_paragraph(paragraph)
                if record is None or not _has_inline_numbered_markers(record.text):
                    rewritten.append(paragraph)
                    continue
                lines = [line.strip() for line in str(getattr(paragraph, "unicode", "") or "").splitlines() if line.strip()]
                if len(lines) < 2:
                    rewritten.append(paragraph)
                    continue
                rewritten.extend(_split_paragraph_by_lines(paragraph, lines))
                split_count += 1
            page.pdf_paragraph = rewritten
        if split_count:
            self.applied_events.append(
                {
                    "action": "split_numbered_paragraph_before_typesetting",
                    "paragraphs": split_count,
                }
            )

    def normalize_body_font_sizes_before_typesetting(self, document: Any) -> None:
        normalized_runs = 0
        samples: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            for paragraph in getattr(page, "pdf_paragraph", []) or []:
                record = self._record_for_paragraph(paragraph)
                if record is None or record.role != "body" or record.policy != "pass_through":
                    continue
                if (
                    not self._needs_scoped_postprocess(paragraph)
                    and id(paragraph) not in self._definition_style_restored_paragraph_ids
                ):
                    continue
                base_style = getattr(paragraph, "pdf_style", None)
                base_size = float(getattr(base_style, "font_size", 0) or 0)
                if base_size <= 0:
                    continue
                paragraph_changes = []
                for item in getattr(paragraph, "pdf_paragraph_composition", []) or []:
                    same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
                    if same_style_unicode is None:
                        continue
                    run_text = str(getattr(same_style_unicode, "unicode", "") or "")
                    style = getattr(same_style_unicode, "pdf_style", None)
                    current_size = float(getattr(style, "font_size", 0) or 0)
                    if not _should_normalize_translated_run_font_size(run_text, current_size, base_size):
                        continue
                    style.font_size = base_size
                    paragraph_changes.append(
                        {
                            "text": run_text[:80],
                            "from": round(current_size, 3),
                            "to": round(base_size, 3),
                        }
                    )
                if not paragraph_changes:
                    continue
                normalized_runs += len(paragraph_changes)
                if len(samples) < 8:
                    samples.append(
                        {
                            "paragraph_id": record.paragraph_id,
                            "page_number": record.page_number,
                            "changes": paragraph_changes[:3],
                        }
                    )
        if normalized_runs:
            self.applied_events.append(
                {
                    "action": "normalize_body_font_sizes_before_typesetting",
                    "runs": normalized_runs,
                    "samples": samples,
                }
            )

    def replace_axis_label_render_units(
        self,
        page: Any,
        render_units: list[Any],
        translation_config: Any,
    ) -> list[Any]:
        from babeldoc.format.pdf.document_il import il_version_1
        from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting

        chars = [getattr(unit, "char", None) for unit in render_units if getattr(unit, "char", None) is not None]
        groups = _page_level_axis_label_groups(chars)
        if not groups:
            return render_units

        raw_page_number = getattr(page, "page_number", None)
        page_number = raw_page_number + 1 if isinstance(raw_page_number, int) else raw_page_number
        typesetter = Typesetting(translation_config)
        fonts = _build_typesetting_fonts(page, typesetter)

        source_char_ids: set[int] = set()
        translated_char_ids: set[int] = set()
        replacement_units = []
        diagnostics = []
        for group in groups:
            source_text = _axis_label_translation_source(_char_group_text(group))
            source_rect = _char_group_rect(group)
            if source_rect is None:
                continue
            if source_text is None:
                source_text = self._infer_axis_label_source_from_context(page_number, group, source_rect)
            if source_text is None:
                continue
            if self._should_skip_page_level_axis_group(page_number, group, source_text):
                continue
            source_text = _restore_micro_unit_from_glyph_fonts(source_text, group)
            source_font_size = _group_font_size(group)
            translated_text = self._translate_axis_label_text(source_text, translation_config)
            paragraph = _build_synthetic_axis_label_paragraph(il_version_1, group, translated_text, source_rect)
            if paragraph is None:
                continue
            typesetter.render_paragraph(paragraph, page, fonts)
            translated_chars = _paragraph_pdf_chars(paragraph)
            if not translated_chars:
                continue
            unit = _AxisLabelRenderUnit.from_group(
                translated_chars,
                anchor_rect=source_rect,
                sort_mode="x",
                preferred_font_size=source_font_size,
            )
            if unit is None:
                continue
            source_char_ids.update(id(char) for char in group)
            translated_char_ids.update(id(char) for char in translated_chars)
            replacement_units.append(unit)
            diagnostics.append(
                {
                    "page_number": page_number,
                    "raw_text": _char_group_text(group),
                    "raw_chars": [
                        {
                            "unicode": str(getattr(char, "char_unicode", "") or ""),
                            "pdf_character_id": getattr(char, "pdf_character_id", None),
                            "font_id": getattr(getattr(char, "pdf_style", None), "font_id", None),
                        }
                        for char in _sorted_axis_chars(group)
                    ],
                    "text": source_text,
                    "translated_text": translated_text,
                    "rect": source_rect,
                    "characters": len(translated_chars),
                    "replacement": "translated_axis_label_rotated_text",
                }
            )

        if not replacement_units:
            return render_units

        replaced_units = [
            unit
            for unit in render_units
            if id(getattr(unit, "char", None)) not in source_char_ids
            and id(getattr(unit, "char", None)) not in translated_char_ids
        ]
        replaced_units.extend(replacement_units)

        self.axis_diagnostics["character_groups"].extend(diagnostics[:24])
        samples = [
            {
                "text": entry["text"][:80],
                "translated_text": entry["translated_text"][:80],
                "rect": entry["rect"],
                "characters": entry["characters"],
            }
            for entry in diagnostics[:8]
        ]
        self.applied_events.append(
            {
                "action": "replace_page_axis_label_render_units",
                "page_number": page_number,
                "groups": len(replacement_units),
                "characters": sum(entry["characters"] for entry in diagnostics),
                "samples": samples,
            }
        )
        return replaced_units

    def _infer_axis_label_source_from_context(
        self,
        page_number: int | None,
        group: list[Any],
        source_rect: tuple[float, float, float, float],
    ) -> str | None:
        if page_number is None:
            return None
        raw_text = _compact_vertical_fragment_text(_char_group_text(group))
        if not raw_text:
            return None
        if "%" not in raw_text:
            return None
        page_records = [
            record
            for record in self.records_by_id.values()
            if record.page_number == page_number and record.rect is not None
        ]
        title_text = _nearest_chart_title_text(page_records, source_rect)
        if title_text is None:
            return None
        title_upper = unicodedata.normalize("NFKC", title_text).upper()
        if "GAIN ERROR" in title_upper:
            return "Gain Error (%)"
        return None

    def _translate_axis_label_text(self, source_text: str, translation_config: Any) -> str:
        with self._lock:
            cached = self._axis_label_translation_cache.get(source_text)
        if cached is not None:
            return cached
        protected_source_text, protected = _protect_technical_tokens_in_text(source_text)
        translated = translation_config.translator.translate(protected_source_text, ignore_cache=True)
        translated = _restore_protected_token_pairs(protected, translated)
        translated = _restore_axis_label_unit(source_text, translated)
        if _axis_label_translation_needs_retry(source_text, translated):
            retried = _retry_translate_axis_label_body_only(source_text, translation_config)
            if retried:
                translated = retried
        translated = _SPACE_COLLAPSE_RE.sub(" ", str(translated or "")).strip()
        if not translated:
            translated = source_text
        with self._lock:
            self._axis_label_translation_cache[source_text] = translated
        return translated

    def reconcile_translation(self) -> None:
        if self._reconciled:
            return
        self._reconciled = True
        for group_id, paragraph_ids in self.groups.items():
            leader_id = self._translated_leader_id(paragraph_ids)
            if leader_id is None:
                continue
            leader_snapshot = self._translations[leader_id]
            changed = 0
            for paragraph_id in paragraph_ids:
                if paragraph_id == leader_id:
                    continue
                paragraph = self.paragraphs_by_id.get(paragraph_id)
                record = self.records_by_id.get(paragraph_id)
                if paragraph is None or record is None:
                    continue
                paragraph.unicode = leader_snapshot.unicode
                paragraph.pdf_paragraph_composition = copy.deepcopy(leader_snapshot.composition)
                changed += 1
            if changed:
                self.applied_events.append(
                    {
                        "action": "reconcile_repeated_edge_text",
                        "group_id": group_id,
                        "leader_id": leader_id,
                        "followers": changed,
                    }
                )

    def write_sidecar(self, path: Path | None = None) -> Path | None:
        sidecar_path = path or (self.working_dir / "doc_translator_ir.json" if self.working_dir else None)
        if sidecar_path is None:
            return None
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        roles = [
            asdict(record.to_role())
            for record in self.records_by_id.values()
            if record.role != "body" or record.policy != "pass_through"
        ]
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategy": "babeldoc_internal_hooks_v1",
            "counts": self._role_counts(),
            "roles": roles,
            "groups": self.groups,
            "diagnostic_samples": self._diagnostic_samples(),
            "axis_diagnostics": self.axis_diagnostics,
            "phase_events": self.phase_events,
            "applied_events": self.applied_events,
        }
        sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return sidecar_path

    def capture_after_translation_snapshot(self, document: Any) -> None:
        self._after_structure_snapshot = self._build_structure_snapshot(document, stage="after_translation")

    def write_structure_snapshot(self, stage: str, path: Path | None = None) -> Path | None:
        snapshot = self._before_structure_snapshot if stage == "before_translation" else self._after_structure_snapshot
        if snapshot is None:
            return None
        snapshot_path = path or (
            self.working_dir / f"doc_translator_structure_{'before' if stage == 'before_translation' else 'after'}.json"
            if self.working_dir
            else None
        )
        if snapshot_path is None:
            return None
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return snapshot_path

    def _diagnostic_samples(self) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        for record in self.records_by_id.values():
            if not _is_diagnostic_sample(record.text):
                continue
            samples.append(
                {
                    "paragraph_id": record.paragraph_id,
                    "page_number": record.page_number,
                    "role": record.role,
                    "policy": record.policy,
                    "text": record.text,
                    "rect": record.rect,
                }
            )
            if len(samples) >= 80:
                break
        if len(samples) < 80:
            for record in self.records_by_id.values():
                if record in samples:
                    continue
                if record.rect is None:
                    continue
                x1, y1, x2, y2 = record.rect
                width = x2 - x1
                height = y2 - y1
                if width > 24 or height < max(width * 2.5, 18):
                    continue
                samples.append(
                    {
                        "paragraph_id": record.paragraph_id,
                        "page_number": record.page_number,
                        "role": record.role,
                        "policy": record.policy,
                        "text": record.text,
                        "rect": record.rect,
                        "diagnostic_reason": "high_narrow_paragraph",
                    }
                )
                if len(samples) >= 80:
                    break
        return samples

    def _build_structure_snapshot(self, document: Any, *, stage: str) -> dict[str, Any]:
        pages_payload: list[dict[str, Any]] = []
        paragraph_total = 0
        for page_index, page in enumerate(getattr(document, "page", []) or []):
            paragraphs_payload: list[dict[str, Any]] = []
            for paragraph_index, paragraph in enumerate(getattr(page, "pdf_paragraph", []) or []):
                paragraph_id = _paragraph_id(paragraph, page_index, paragraph_index)
                record = self.records_by_id.get(paragraph_id)
                paragraph_payload = {
                    "paragraph_id": paragraph_id,
                    "page_number": _page_number(page, page_index),
                    "paragraph_index": paragraph_index + 1,
                    "unicode": str(getattr(paragraph, "unicode", "") or ""),
                    "rect": _box_rect(getattr(paragraph, "box", None)),
                    "vertical": bool(getattr(paragraph, "vertical", False)),
                    "layout_label": getattr(paragraph, "layout_label", None),
                    "xobj_id": getattr(paragraph, "xobj_id", None),
                    "role": record.role if record is not None else "body",
                    "policy": record.policy if record is not None else "pass_through",
                    "source_text": record.text if record is not None else None,
                    "source_rect": record.rect if record is not None else None,
                    "protected_tokens": self._protected_tokens.get(paragraph_id, []),
                    "composition": _composition_debug_payload(getattr(paragraph, "pdf_paragraph_composition", []) or []),
                }
                translation_snapshot = self._translations.get(paragraph_id)
                if translation_snapshot is not None:
                    paragraph_payload["translated_unicode_snapshot"] = translation_snapshot.unicode
                paragraphs_payload.append(paragraph_payload)
            paragraph_total += len(paragraphs_payload)
            pages_payload.append(
                {
                    "page_number": _page_number(page, page_index),
                    "paragraphs": paragraphs_payload,
                }
            )
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "paragraph_total": paragraph_total,
            "counts": self._role_counts(),
            "pages": pages_payload,
            "axis_diagnostics": copy.deepcopy(self.axis_diagnostics),
            "applied_events": copy.deepcopy(self.applied_events),
        }

    def _capture_source_layouts(self, records: list[_ParagraphRecord]) -> None:
        self._source_layouts.clear()
        for record in records:
            if record.role != "vertical_label" or record.policy != "preserve":
                continue
            paragraph = self.paragraphs_by_id.get(record.paragraph_id)
            if paragraph is None:
                continue
            self._source_layouts[record.paragraph_id] = _TranslationSnapshot(
                unicode=str(getattr(paragraph, "unicode", "") or ""),
                composition=copy.deepcopy(getattr(paragraph, "pdf_paragraph_composition", []) or []),
            )

    def _collect_records(self, document: Any) -> list[_ParagraphRecord]:
        records: list[_ParagraphRecord] = []
        pages = getattr(document, "page", []) or []
        self.paragraphs_by_id = {}
        for page_index, page in enumerate(pages):
            page_number = _page_number(page, page_index)
            page_rect = _page_rect(page)
            paragraphs = getattr(page, "pdf_paragraph", []) or []
            for paragraph_index, paragraph in enumerate(paragraphs):
                text = str(getattr(paragraph, "unicode", "") or "")
                if not text.strip():
                    continue
                paragraph_id = _paragraph_id(paragraph, page_index, paragraph_index)
                record = _ParagraphRecord(
                    paragraph_id=paragraph_id,
                    object_id=id(paragraph),
                    page_number=page_number,
                    page_index=page_index,
                    paragraph_index=paragraph_index,
                    text=text,
                    canonical_text=_canonical_text(text),
                    rect=_box_rect(getattr(paragraph, "box", None)),
                    page_rect=page_rect,
                    vertical=bool(getattr(paragraph, "vertical", False)),
                    layout_label=getattr(paragraph, "layout_label", None),
                    xobj_id=getattr(paragraph, "xobj_id", None),
                )
                records.append(record)
                self.paragraphs_by_id[paragraph_id] = paragraph
        return records

    def _classify_repeated_edge_text(self, records: list[_ParagraphRecord]) -> None:
        by_text: dict[str, list[_ParagraphRecord]] = {}
        for record in records:
            if record.policy != "pass_through":
                continue
            if not _eligible_repeated_text(record):
                continue
            by_text.setdefault(record.canonical_text, []).append(record)

        total_pages = len({record.page_number for record in records})
        if total_pages < 3:
            return
        min_pages = 3
        for canonical_text, candidates in by_text.items():
            pages = {record.page_number for record in candidates}
            if len(pages) < min_pages:
                continue
            edge_candidates = [record for record in candidates if _is_edge_band(record)]
            if len(edge_candidates) / len(candidates) < 0.8:
                continue
            group_id = f"repeated-edge:{hashlib.sha1(canonical_text.encode('utf-8')).hexdigest()[:12]}"
            self.groups[group_id] = [record.paragraph_id for record in edge_candidates]
            for record in edge_candidates:
                _mark(
                    record,
                    "running_edge_text",
                    "translate_once",
                    0.88,
                    ("same normalized text repeated near page edge",),
                    group_id=group_id,
                )

    def _build_toc_alignment(self, records: list[_ParagraphRecord]) -> None:
        grouped_records: dict[tuple[int, str], list[_ParagraphRecord]] = {}
        for record in records:
            if record.role != "toc_entry":
                continue
            toc_parts = _split_toc_entry(record.text)
            if toc_parts is None:
                continue
            grouped_records.setdefault((record.page_index, _toc_column_key(record)), []).append(record)

        for column_records in grouped_records.values():
            prefix_widths = []
            for record in column_records:
                toc_parts = _split_toc_entry(record.text)
                if toc_parts is None:
                    continue
                source_title, source_leader, _page_number = toc_parts
                prefix_widths.append(_display_width(f"{source_title}{source_leader}"))
            if not prefix_widths:
                continue
            prefix_widths.sort()
            anchor_width = prefix_widths[min(len(prefix_widths) - 1, max(0, int(len(prefix_widths) * 0.85)))]
            for record in column_records:
                self._toc_prefix_width_by_id[record.paragraph_id] = anchor_width

    def _translated_leader_id(self, paragraph_ids: list[str]) -> str | None:
        for paragraph_id in paragraph_ids:
            record = self.records_by_id.get(paragraph_id)
            snapshot = self._translations.get(paragraph_id)
            if record is None or snapshot is None:
                continue
            if _canonical_text(snapshot.unicode) and _canonical_text(snapshot.unicode) != record.canonical_text:
                return paragraph_id
        return None

    def _record_for_paragraph(self, paragraph: Any) -> _ParagraphRecord | None:
        debug_id = str(getattr(paragraph, "debug_id", "") or "")
        if debug_id and debug_id in self.records_by_id:
            return self.records_by_id[debug_id]
        return self.records_by_object_id.get(id(paragraph))

    def _role_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records_by_id.values():
            counts[record.role] = counts.get(record.role, 0) + 1
        return counts


def babeldoc_ir_sidecar_path(output_path: Path) -> Path:
    return output_path.with_suffix(f"{output_path.suffix}.babeldoc-ir.json")


def babeldoc_structure_snapshot_path(output_path: Path, stage: str) -> Path:
    suffix = "before" if stage == "before_translation" else "after"
    return output_path.with_suffix(f"{output_path.suffix}.babeldoc-structure-{suffix}.json")


def _mark(
    record: _ParagraphRecord,
    role: str,
    policy: str,
    confidence: float,
    evidence: tuple[str, ...],
    *,
    group_id: str | None = None,
) -> None:
    record.role = role
    record.policy = policy
    record.confidence = confidence
    record.evidence = evidence
    record.group_id = group_id


def _paragraph_id(paragraph: Any, page_index: int, paragraph_index: int) -> str:
    debug_id = str(getattr(paragraph, "debug_id", "") or "")
    if debug_id:
        return debug_id
    return f"p{page_index + 1}:{paragraph_index + 1}"


def _page_number(page: Any, page_index: int) -> int:
    page_number = getattr(page, "page_number", None)
    if isinstance(page_number, int):
        return page_number + 1 if page_number == page_index else page_number
    return page_index + 1


def _page_rect(page: Any) -> tuple[float, float, float, float] | None:
    for box_holder_name in ("cropbox", "mediabox"):
        box_holder = getattr(page, box_holder_name, None)
        rect = _box_rect(getattr(box_holder, "box", None))
        if rect is not None:
            return rect
    return None


def _box_rect(box: Any) -> tuple[float, float, float, float] | None:
    values = (getattr(box, "x", None), getattr(box, "y", None), getattr(box, "x2", None), getattr(box, "y2", None))
    if any(value is None for value in values):
        return None
    rect = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in rect):
        return None
    return rect


def _set_box_rect(box: Any, rect: tuple[float, float, float, float] | None) -> None:
    if box is None or rect is None:
        return
    box.x, box.y, box.x2, box.y2 = rect


def _canonical_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    return _SPACE_COLLAPSE_RE.sub("", normalized).strip()


def _is_preserve_candidate(record: _ParagraphRecord) -> bool:
    text = unicodedata.normalize("NFKC", record.text).strip()
    collapsed = _SPACE_COLLAPSE_RE.sub("", text)
    if not collapsed or len(collapsed) > 24:
        return _is_compact_technical_label_record(record)
    if _is_compact_technical_label_record(record):
        return True
    has_spacing = bool(_SPACE_COLLAPSE_RE.search(text))
    if _PAGE_NUMBER_RE.fullmatch(text):
        return True
    if _ROMAN_PAGE_RE.fullmatch(text) and _is_edge_band(record):
        return True
    if _NUMERIC_OR_SYMBOL_RE.fullmatch(collapsed):
        return True
    if not has_spacing and _TECHNICAL_TOKEN_RE.fullmatch(text):
        return True
    if not has_spacing and _SHORT_UPPER_TOKEN_RE.fullmatch(collapsed) and collapsed in _TECHNICAL_UPPER_TOKENS:
        return True
    return False


def _is_compact_technical_label_record(record: _ParagraphRecord) -> bool:
    if record.layout_label != "fallback_line" or record.rect is None:
        return False
    text = unicodedata.normalize("NFKC", record.text).strip()
    if not text or "\n" in text:
        return False
    compact = _SPACE_COLLAPSE_RE.sub("", text)
    if len(compact) < 3 or len(compact) > 48:
        return False
    x1, y1, x2, y2 = record.rect
    width = x2 - x1
    height = y2 - y1
    if height > 14.0 or width > 180.0:
        return False
    if _TECHNICAL_NUMBER_UNIT_RE.search(text) or _TECHNICAL_RATIO_TOKEN_RE.search(text):
        return True
    if _TECHNICAL_IDENTIFIER_RE.search(compact):
        return True
    if re.search(r"[=()/±°^/_-]|[A-Z]\d|\d[A-Z]", text):
        return True
    if record.xobj_id not in {None, 0} and any(char.isupper() for char in compact):
        word_count = len(text.split())
        if word_count <= 4:
            return True
    return False


def _looks_like_mergeable_line_fragment(left_text: str, right_text: str) -> bool:
    left = unicodedata.normalize("NFKC", left_text).strip()
    right = unicodedata.normalize("NFKC", right_text).strip()
    if not left or not right:
        return False
    if _NUMERIC_OR_SYMBOL_RE.fullmatch(left) and _NUMERIC_OR_SYMBOL_RE.fullmatch(right):
        return False
    combined = f"{left}{right}"
    if len(combined) < 8:
        return False
    if not any(char.isalpha() for char in combined):
        return False
    if _PAGE_NUMBER_RE.fullmatch(left) or _PAGE_NUMBER_RE.fullmatch(right):
        return False
    return (
        _looks_like_broken_word_boundary(left, right)
        or _looks_like_prose_fragment(left)
        or _looks_like_prose_fragment(right)
    )


def _looks_like_broken_word_boundary(left: str, right: str) -> bool:
    return bool(
        left
        and right
        and left[-1].isalpha()
        and right[0].isalpha()
        and (left[-1].islower() or right[0].islower())
    )


def _looks_like_prose_fragment(text: str) -> bool:
    letters = sum(1 for char in text if char.isalpha())
    if letters < 3:
        return False
    return bool(re.search(r"[a-z]", text)) or bool(re.search(r"\s", text))


def _same_baseline_close_gap(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> tuple[bool, str]:
    if right_rect[0] < left_rect[0]:
        return False, "right_before_left"
    left_height = max(left_rect[3] - left_rect[1], 1.0)
    right_height = max(right_rect[3] - right_rect[1], 1.0)
    overlap = min(left_rect[3], right_rect[3]) - max(left_rect[1], right_rect[1])
    if overlap / min(left_height, right_height) < 0.62:
        return False, "low_vertical_overlap"
    center_delta = abs(((left_rect[1] + left_rect[3]) / 2) - ((right_rect[1] + right_rect[3]) / 2))
    if center_delta > max(left_height, right_height) * 0.45:
        return False, "centerline_delta_too_large"
    gap = right_rect[0] - left_rect[2]
    gap_limit = max(4.0, min(left_height, right_height) * 0.55)
    if not (-1.0 <= gap <= gap_limit):
        return False, f"gap_out_of_range:{round(gap, 3)}>{round(gap_limit, 3)}"
    return True, "ok"


def _paragraph_visual_sort_key(paragraph: Any, original_index: int) -> tuple[float, float, float, int]:
    rect = _box_rect(getattr(paragraph, "box", None))
    if rect is None:
        return (float("inf"), float("inf"), float("inf"), original_index)
    x1, y1, x2, y2 = rect
    return (-y2, x1, -y1, original_index)


def _looks_like_potential_same_line_fragment_pair(left: Any, right: Any) -> bool:
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or right_rect is None:
        return False
    left_text = str(getattr(left, "unicode", "") or "").strip()
    right_text = str(getattr(right, "unicode", "") or "").strip()
    if not left_text or not right_text:
        return False
    left_height = max(left_rect[3] - left_rect[1], 1.0)
    right_height = max(right_rect[3] - right_rect[1], 1.0)
    center_delta = abs(((left_rect[1] + left_rect[3]) / 2) - ((right_rect[1] + right_rect[3]) / 2))
    horizontal_gap = right_rect[0] - left_rect[2]
    return center_delta <= max(left_height, right_height) * 0.8 and horizontal_gap <= max(18.0, min(left_height, right_height) * 2.0)


def _group_overlapping_same_baseline_paragraphs(paragraphs: list[Any]) -> list[list[int]]:
    ordered = [
        (index, paragraph)
        for index, paragraph in enumerate(paragraphs)
        if _is_overlap_fragment_candidate(paragraph) and _box_rect(getattr(paragraph, "box", None)) is not None
    ]
    if len(ordered) < 3:
        return []
    ordered.sort(key=lambda item: _paragraph_visual_sort_key(item[1], item[0]))
    groups: list[list[int]] = []
    current: list[int] = []
    current_anchor = None
    for index, paragraph in ordered:
        rect = _box_rect(getattr(paragraph, "box", None))
        if rect is None:
            continue
        if (
            current
            and current_anchor is not None
            and getattr(paragraphs[current[-1]], "xobj_id", None) == getattr(paragraph, "xobj_id", None)
            and _same_overlap_fragment_baseline(current_anchor, rect)
        ):
            current.append(index)
            current_anchor = _rect_union([current_anchor, rect]) or current_anchor
            continue
        if len(current) >= 3:
            groups.append(current)
        current = [index]
        current_anchor = rect
    if len(current) >= 3:
        groups.append(current)
    return groups


def _is_overlap_fragment_candidate(paragraph: Any) -> bool:
    if getattr(paragraph, "layout_label", None) not in {"plain text", "table_footnote"}:
        return False
    text = unicodedata.normalize("NFKC", str(getattr(paragraph, "unicode", "") or "")).strip()
    if len(text) < 1:
        return False
    return any(char.isalpha() for char in text) or text in {":", "："}


def _same_overlap_fragment_baseline(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    left_height = max(left_rect[3] - left_rect[1], 1.0)
    right_height = max(right_rect[3] - right_rect[1], 1.0)
    overlap = min(left_rect[3], right_rect[3]) - max(left_rect[1], right_rect[1])
    if overlap / min(left_height, right_height) >= 0.4:
        return True
    center_delta = abs(((left_rect[1] + left_rect[3]) / 2) - ((right_rect[1] + right_rect[3]) / 2))
    return center_delta <= max(left_height, right_height) * 0.55


def _find_subsuming_same_line_anchor(
    paragraphs: list[Any],
    candidate_index: int,
    removed_indices: set[int],
) -> int | None:
    candidate = paragraphs[candidate_index]
    candidate_text = unicodedata.normalize("NFKC", str(getattr(candidate, "unicode", "") or "")).strip()
    candidate_rect = _box_rect(getattr(candidate, "box", None))
    if not candidate_text or candidate_rect is None:
        return None
    if getattr(candidate, "layout_label", None) not in {"plain text", "table_footnote"}:
        return None
    if len(_SPACE_COLLAPSE_RE.sub("", candidate_text)) < 24:
        return None
    best_index: int | None = None
    best_score: tuple[int, float] | None = None
    for anchor_index, anchor in enumerate(paragraphs):
        if anchor_index == candidate_index or anchor_index in removed_indices:
            continue
        if getattr(anchor, "xobj_id", None) != getattr(candidate, "xobj_id", None):
            continue
        anchor_text = unicodedata.normalize("NFKC", str(getattr(anchor, "unicode", "") or "")).strip()
        anchor_rect = _box_rect(getattr(anchor, "box", None))
        if not anchor_text or anchor_rect is None:
            continue
        if len(anchor_text) <= len(candidate_text) or candidate_text not in anchor_text:
            continue
        if not _same_overlap_fragment_baseline(anchor_rect, candidate_rect):
            continue
        if not _rect_contains_with_tolerance(anchor_rect, candidate_rect, 2.0):
            continue
        if not _paragraph_contains_matching_fragment(anchor, candidate_text, candidate_rect):
            continue
        score = (len(anchor_text), _horizontal_overlap_width(anchor_rect, candidate_rect))
        if best_score is None or score > best_score:
            best_score = score
            best_index = anchor_index
    return best_index


def _rect_contains_with_tolerance(
    outer_rect: tuple[float, float, float, float],
    inner_rect: tuple[float, float, float, float],
    tolerance: float,
) -> bool:
    return (
        outer_rect[0] <= inner_rect[0] + tolerance
        and outer_rect[1] <= inner_rect[1] + tolerance
        and outer_rect[2] >= inner_rect[2] - tolerance
        and outer_rect[3] >= inner_rect[3] - tolerance
    )


def _paragraph_contains_matching_fragment(
    paragraph: Any,
    fragment_text: str,
    fragment_rect: tuple[float, float, float, float],
) -> bool:
    normalized_fragment = unicodedata.normalize("NFKC", str(fragment_text or "")).strip()
    if not normalized_fragment:
        return False
    for item in getattr(paragraph, "pdf_paragraph_composition", []) or []:
        item_text = unicodedata.normalize("NFKC", _composition_text([item])).strip()
        item_rect = _composition_item_rect(item)
        if item_rect is None or item_text != normalized_fragment:
            continue
        if _rects_close(item_rect, fragment_rect, tolerance=1.2):
            return True
    return False


def _rects_close(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
    *,
    tolerance: float,
) -> bool:
    return all(abs(left - right) <= tolerance for left, right in zip(left_rect, right_rect, strict=True))


def _looks_like_overlapping_fragment_cluster(group: list[tuple[int, Any]]) -> bool:
    if len(group) < 3:
        return False
    entries = []
    for _index, paragraph in group:
        rect = _box_rect(getattr(paragraph, "box", None))
        text = unicodedata.normalize("NFKC", str(getattr(paragraph, "unicode", "") or "")).strip()
        if rect is None or not text:
            continue
        entries.append((paragraph, rect, text))
    if len(entries) < 3:
        return False
    anchor_paragraph, anchor_rect, anchor_text = max(
        entries,
        key=lambda item: (len(_SPACE_COLLAPSE_RE.sub("", item[2])), item[1][2] - item[1][0]),
    )
    if len(_SPACE_COLLAPSE_RE.sub("", anchor_text)) < 24:
        return False
    overlapping = 0
    short_fragments = 0
    for paragraph, rect, text in entries:
        if paragraph is anchor_paragraph:
            continue
        if _horizontal_overlap_width(anchor_rect, rect) <= 0 and rect[0] > anchor_rect[2] + 6.0:
            continue
        overlapping += 1
        if len(_SPACE_COLLAPSE_RE.sub("", text)) <= 6:
            short_fragments += 1
    return overlapping >= 3 and short_fragments >= 2


def _overlapping_fragment_anchor(group: list[tuple[int, Any]]) -> tuple[int, Any]:
    return max(
        group,
        key=lambda item: (
            len(_SPACE_COLLAPSE_RE.sub("", str(getattr(item[1], "unicode", "") or ""))),
            ((_box_rect(getattr(item[1], "box", None)) or (0.0, 0.0, 0.0, 0.0))[2] - (_box_rect(getattr(item[1], "box", None)) or (0.0, 0.0, 0.0, 0.0))[0]),
        ),
    )


def _should_absorb_overlapping_fragment(left: Any, right: Any) -> bool:
    if getattr(left, "xobj_id", None) != getattr(right, "xobj_id", None):
        return False
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or right_rect is None or not _same_overlap_fragment_baseline(left_rect, right_rect):
        return False
    if right_rect[0] < left_rect[0] - 1.0:
        return False
    gap = right_rect[0] - left_rect[2]
    overlap = _horizontal_overlap_width(left_rect, right_rect)
    return overlap > 0 or gap <= 6.0


def _should_absorb_overlapping_rect_fragment(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    if not _same_overlap_fragment_baseline(left_rect, right_rect):
        return False
    gap = right_rect[0] - left_rect[2]
    overlap = _horizontal_overlap_width(left_rect, right_rect)
    return overlap > 0 or gap <= 6.0


def _horizontal_overlap_width(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> float:
    return min(left_rect[2], right_rect[2]) - max(left_rect[0], right_rect[0])


def _wrapped_decimal_continuation_score(
    left: Any,
    right: Any,
) -> tuple[float, float] | None:
    if getattr(left, "xobj_id", None) != getattr(right, "xobj_id", None):
        return None
    left_text = unicodedata.normalize("NFKC", str(getattr(left, "unicode", "") or "")).strip()
    right_text = unicodedata.normalize("NFKC", str(getattr(right, "unicode", "") or "")).strip()
    if re.search(r"[-+±]?\d+\.$", left_text) is None:
        return None
    if re.match(r"^\d+[A-Za-z%°ΩΩµμ]", right_text) is None:
        return None
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or right_rect is None:
        return None
    left_height = max(left_rect[3] - left_rect[1], 1.0)
    right_height = max(right_rect[3] - right_rect[1], 1.0)
    if right_rect[1] >= left_rect[1] - max(2.0, left_height * 0.2):
        return None
    if right_rect[0] > left_rect[0] + max(8.0, left_height * 0.6):
        return None
    if abs(right_rect[3] - left_rect[3]) > max(left_height, right_height) * 0.35:
        return None
    return (left_rect[1] - right_rect[1], abs(right_rect[0] - left_rect[0]))


def _merge_paragraphs(left: Any, right: Any, separator: str | None = None) -> None:
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    joiner = separator
    if joiner is None:
        joiner = ""
        if left_rect is not None and right_rect is not None and right_rect[0] - left_rect[2] > 1.5:
            joiner = " "
    left.unicode = f"{str(getattr(left, 'unicode', '') or '')}{joiner}{str(getattr(right, 'unicode', '') or '')}"
    left.pdf_paragraph_composition = list(getattr(left, "pdf_paragraph_composition", []) or []) + list(
        getattr(right, "pdf_paragraph_composition", []) or []
    )
    if left_rect is not None and right_rect is not None:
        _set_box_rect(getattr(left, "box", None), _rect_union([left_rect, right_rect]))
    left.optimal_scale = None


def _merge_paragraphs_with_overlap(left: Any, right: Any) -> None:
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    left_text = str(getattr(left, "unicode", "") or "")
    right_text = str(getattr(right, "unicode", "") or "")
    if not right_text:
        return
    merged_text = _merged_text_with_overlap(left_text, right_text, left_rect, right_rect)
    joiner = None
    if merged_text != left_text and left_rect is not None and right_rect is not None:
        joiner = " " if right_rect[0] - left_rect[2] > 1.5 else ""
    _merge_paragraphs(left, right, separator=joiner)
    left.unicode = merged_text


def _merged_text_with_overlap(
    left_text: str,
    right_text: str,
    left_rect: tuple[float, float, float, float] | None,
    right_rect: tuple[float, float, float, float] | None,
) -> str:
    if not right_text:
        return left_text
    if right_text in left_text:
        return left_text
    max_overlap = min(len(left_text), len(right_text))
    for overlap in range(max_overlap, 1, -1):
        if left_text.endswith(right_text[:overlap]):
            return f"{left_text}{right_text[overlap:]}"
    if (
        left_rect is not None
        and right_rect is not None
        and _horizontal_overlap_width(left_rect, right_rect) > 0
        and right_rect[2] <= left_rect[2] + 0.5
    ):
        return left_text
    joiner = ""
    if left_rect is not None and right_rect is not None and right_rect[0] - left_rect[2] > 1.5:
        joiner = " "
    return f"{left_text}{joiner}{right_text}"


class _AxisLabelRenderUnit:
    def __init__(
        self,
        chars: list[Any],
        render_order: int,
        sub_render_order: int,
        xobj_id: str | None,
        anchor_rect: tuple[float, float, float, float] | None = None,
        preferred_font_size: float | None = None,
    ) -> None:
        self.chars = chars
        self.render_order = render_order
        self.sub_render_order = sub_render_order
        self.xobj_id = xobj_id
        self.anchor_rect = anchor_rect
        self.preferred_font_size = preferred_font_size

    @classmethod
    def from_group(
        cls,
        group: list[Any],
        *,
        anchor_rect: tuple[float, float, float, float] | None = None,
        sort_mode: str = "y",
        preferred_font_size: float | None = None,
    ) -> "_AxisLabelRenderUnit | None":
        if not _can_render_axis_label_as_group(group):
            return None
        chars = _sorted_axis_chars(group, sort_mode=sort_mode)
        render_order = min(getattr(char, "render_order", 100) or 100 for char in chars)
        sub_render_order = min(getattr(char, "sub_render_order", 0) or 0 for char in chars)
        return cls(
            chars,
            render_order,
            sub_render_order,
            getattr(chars[0], "xobj_id", None),
            anchor_rect=anchor_rect,
            preferred_font_size=preferred_font_size,
        )

    def get_sort_key(self) -> tuple[int, int]:
        return self.render_order, self.sub_render_order

    def render(self, draw_op: Any, context: Any) -> None:
        first = self.chars[0]
        anchor_rect = self.anchor_rect or _char_group_rect(self.chars)
        text_rect = _char_group_rect(self.chars)
        current_font_size = _group_font_size(self.chars)
        target_font_size = self.preferred_font_size or current_font_size or first.pdf_style.font_size
        if _group_contains_cjk(self.chars):
            target_font_size = _CJK_AXIS_LABEL_FONT_SIZE
        final_scale = 1.0
        if anchor_rect is None:
            anchor_x = first.box.x2
            anchor_y = first.box.y
        else:
            anchor_width = max(anchor_rect[2] - anchor_rect[0], 1.0)
            anchor_height = max(anchor_rect[3] - anchor_rect[1], 1.0)
            anchor_y = anchor_rect[1]
            cross_padding = min(_VERTICAL_AXIS_LABEL_CROSS_PADDING, anchor_width * 0.18)
            max_cross_font_size = max(anchor_width - (cross_padding * 2.0), 0.1)
            target_font_size = min(target_font_size, max_cross_font_size)
            anchor_x = anchor_rect[0] + cross_padding + target_font_size
        draw_op.append(b"q ")
        context.pdf_creator.render_graphic_state(draw_op, first.pdf_style.graphic_state)
        if anchor_rect is not None and text_rect is not None:
            anchor_height = max(anchor_rect[3] - anchor_rect[1], 1.0)
            font_ratio = 1.0
            if current_font_size is not None and current_font_size > 0:
                font_ratio = target_font_size / current_font_size
            final_scale = font_ratio
            top_padding = target_font_size * _VERTICAL_AXIS_LABEL_TOP_PADDING_RATIO
            bottom_padding = target_font_size * _VERTICAL_AXIS_LABEL_BOTTOM_PADDING_RATIO
            usable_start = anchor_rect[1] + top_padding
            usable_end = anchor_rect[3] - bottom_padding
            positioned_chars: list[tuple[Any, float, float]] = []
            baseline_offset = 0.0
            for index, char in enumerate(self.chars):
                font_size = max(char.pdf_style.font_size * final_scale, 0.1)
                positioned_chars.append((char, font_size, baseline_offset))
                advance = _vertical_axis_label_advance(char, font_size)
                if index < len(self.chars) - 1:
                    advance += font_size * _VERTICAL_AXIS_LABEL_INTER_CHAR_GAP_RATIO
                baseline_offset += advance
            rendered_height = baseline_offset if positioned_chars else 0.0
            available_height = max(usable_end - usable_start, 1.0)
            anchor_y = anchor_rect[1] + max(anchor_height - rendered_height, 0.0) / 2.0
            if rendered_height <= available_height:
                anchor_y = usable_start + max(available_height - rendered_height, 0.0) / 2.0
            for char, font_size, char_offset in positioned_chars:
                font_id = char.pdf_style.font_id
                encoding_length = self._encoding_length(context, font_id)
                if encoding_length is None:
                    continue
                baseline_y = anchor_y + char_offset
                draw_op.append(f"BT 0 1 -1 0 {anchor_x:f} {baseline_y:f} Tm ".encode())
                draw_op.append(f"/{font_id} {font_size:f} Tf ".encode())
                draw_op.append(f"<{char.pdf_character_id:0{encoding_length * 2}x}>".upper().encode())
                draw_op.append(b" Tj ET ")
            draw_op.append(b"Q \n")
            return

        draw_op.append(b"BT ")
        draw_op.append(f"0 1 -1 0 {anchor_x:f} {anchor_y:f} Tm ".encode())
        previous_font = None
        for char in self.chars:
            font_id = char.pdf_style.font_id
            font_size = target_font_size
            encoding_length = self._encoding_length(context, font_id)
            if encoding_length is None:
                continue
            if font_id != previous_font:
                draw_op.append(f"/{font_id} {font_size:f} Tf ".encode())
                previous_font = font_id
            draw_op.append(f"<{char.pdf_character_id:0{encoding_length * 2}x}>".upper().encode())
            draw_op.append(b" Tj ")
        draw_op.append(b"ET Q \n")

    def _encoding_length(self, context: Any, font_id: str | None) -> int | None:
        if self.xobj_id in context.xobj_encoding_length_map:
            encoding_length = context.xobj_encoding_length_map[self.xobj_id].get(font_id)
        else:
            encoding_length = context.page_encoding_length_map.get(font_id)
        if encoding_length is None:
            encoding_length = context.all_encoding_length_map.get(font_id)
        return encoding_length


def _can_render_axis_label_as_group(group: list[Any]) -> bool:
    chars = _sorted_axis_chars(group)
    if not chars:
        return False
    first = chars[0]
    xobj_id = getattr(first, "xobj_id", None)
    for char in chars:
        style = getattr(char, "pdf_style", None)
        if getattr(style, "font_id", None) is None or getattr(style, "font_size", None) is None:
            return False
        if getattr(char, "xobj_id", None) != xobj_id:
            return False
        if getattr(char, "pdf_character_id", None) is None:
            return False
    return True


def _group_font_size(group: list[Any]) -> float | None:
    sizes = []
    for char in group:
        style = getattr(char, "pdf_style", None)
        size = getattr(style, "font_size", None)
        if isinstance(size, (int, float)) and math.isfinite(size) and size > 0:
            sizes.append(float(size))
    if not sizes:
        return None
    sizes.sort()
    return sizes[len(sizes) // 2]


def _group_contains_cjk(group: list[Any]) -> bool:
    for char in group:
        text = str(getattr(char, "char_unicode", "") or "")
        if any("\u4e00" <= symbol <= "\u9fff" for symbol in text):
            return True
    return False


def _vertical_axis_label_advance(char: Any, font_size: float) -> float:
    text = str(getattr(char, "char_unicode", "") or "")
    if not text:
        return font_size * _VERTICAL_AXIS_LABEL_PUNCT_ADVANCE_RATIO
    if text.isspace():
        return font_size * _VERTICAL_AXIS_LABEL_SPACE_ADVANCE_RATIO
    if any("\u4e00" <= symbol <= "\u9fff" for symbol in text):
        return font_size * _VERTICAL_AXIS_LABEL_CJK_ADVANCE_RATIO
    if text.isascii() and any(symbol.isalnum() for symbol in text):
        return font_size * _VERTICAL_AXIS_LABEL_LATIN_ADVANCE_RATIO
    return font_size * _VERTICAL_AXIS_LABEL_PUNCT_ADVANCE_RATIO


def _sorted_axis_chars(group: list[Any], *, sort_mode: str = "y") -> list[Any]:
    items = []
    for char in group:
        rect = _box_rect(getattr(char, "box", None))
        if rect is None:
            continue
        items.append((rect, char))
    if sort_mode == "x":
        ordered = sorted(items, key=lambda item: (item[0][0], item[0][1]))
    else:
        ordered = sorted(items, key=lambda item: (item[0][1], item[0][0]))
    return [char for _rect, char in ordered]


def _axis_label_translation_source(text: str) -> str | None:
    for normalized in _axis_label_text_variants(text):
        if _looks_like_invalid_axis_noise(normalized):
            continue
        unit_match = re.fullmatch(r"(?P<body>[A-Za-z][A-Za-z]+(?:[A-Za-z]+)?)\((?P<unit>[^()]+)\)", normalized)
        if unit_match is not None:
            expanded_body = _ACRONYM_BOUNDARY_RE.sub(" ", _CAMEL_BOUNDARY_RE.sub(" ", unit_match.group("body")))
            expanded_body = _SPACE_COLLAPSE_RE.sub(" ", expanded_body).strip()
            expanded = f"{expanded_body} ({unit_match.group('unit')})"
            if _AXIS_LABEL_TEXT_RE.fullmatch(expanded):
                return expanded
        plain = _normalize_plain_axis_label_text(normalized)
        if plain is not None:
            return plain
    return None


def _nearest_chart_title_text(
    records: list[_ParagraphRecord],
    source_rect: tuple[float, float, float, float],
) -> str | None:
    source_center_x = _rect_center_x(source_rect)
    source_top = source_rect[3]
    best_text: str | None = None
    best_score: tuple[float, float, float] | None = None
    for record in records:
        rect = record.rect
        if rect is None:
            continue
        text = unicodedata.normalize("NFKC", str(record.text or "")).strip()
        if not text or not any(char.isalpha() for char in text):
            continue
        if record.vertical:
            continue
        gap = rect[1] - source_top
        if gap < 12.0 or gap > 120.0:
            continue
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        if width < 40.0 or height > 18.0:
            continue
        if rect[0] < source_rect[0] + 20.0:
            continue
        center_dx = abs(_rect_center_x(rect) - (source_center_x + 110.0))
        score = (gap, center_dx, abs(width - 120.0))
        if best_score is None or score < best_score:
            best_score = score
            best_text = text
    return best_text


def _is_strong_axis_label_source_text(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not normalized:
        return False
    if _TRAILING_UNIT_PARENS_RE.search(normalized) is not None:
        return True
    plain = _normalize_plain_axis_label_text(normalized)
    if plain is None:
        return False
    words = plain.split(" ")
    if len(words) < 2:
        return False
    content_words = [
        word
        for word in words
        if word.casefold() not in _AXIS_LABEL_CONNECTOR_WORDS
    ]
    return any(len(word) >= 4 for word in content_words)


def _axis_label_text_variants(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not normalized:
        return ()
    reversed_text = normalized[::-1].strip()
    if reversed_text and reversed_text != normalized:
        return (normalized, reversed_text)
    return (normalized,)


def _normalize_plain_axis_label_text(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not normalized:
        return None
    if _looks_like_invalid_axis_noise(normalized):
        return None
    normalized = re.sub(r"(?<=[A-Za-z])[^\w\s'-]+(?=[A-Za-z])", " ", normalized)
    normalized = re.sub(r"(?<=[A-Za-z])(of|and|vs|per|from|to|in)(?=[A-Z])", r" \1 ", normalized)
    normalized = _ACRONYM_BOUNDARY_RE.sub(" ", _CAMEL_BOUNDARY_RE.sub(" ", normalized))
    normalized = _SPACE_COLLAPSE_RE.sub(" ", normalized)
    if len(normalized) > 64:
        return None
    words = normalized.split(" ")
    if not words:
        return None
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", word) for word in words):
        return None
    if any(len(word) == 1 for word in words):
        return None
    letters = sum(1 for char in normalized if char.isalpha())
    if letters < 4:
        return None
    if len(words) == 1:
        if len(words[0]) < 4:
            return None
        return normalized

    content_words = [
        word
        for word in words
        if word.casefold() not in _AXIS_LABEL_CONNECTOR_WORDS
    ]
    if not content_words:
        return None
    if not any(len(word) >= 4 or word.isupper() for word in content_words):
        return None
    return normalized


def _looks_like_invalid_axis_noise(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    compact = _SPACE_COLLAPSE_RE.sub("", normalized)
    if len(compact) < 5:
        return False
    if re.search(r"[A-Z]{2,}$", compact) and re.search(r"[a-z]{3,}", compact):
        if not re.search(r"[ _/\-()]", normalized):
            return True
    if compact.count("s") >= 3 and re.search(r"[A-Z]{2}$", compact):
        return True
    return False


def _restore_axis_label_unit(source_text: str, translated_text: str) -> str:
    source_match = _TRAILING_UNIT_PARENS_RE.search(str(source_text or "").strip())
    if source_match is None:
        return translated_text
    source_unit = source_match.group(1).strip()
    translated = str(translated_text or "").strip()
    if not translated:
        return f"({source_unit})"
    translated_match = _TRAILING_UNIT_PARENS_RE.search(translated)
    if translated_match is not None:
        prefix = translated[: translated_match.start()].rstrip()
        return f"{prefix} ({source_unit})".strip()
    return f"{translated} ({source_unit})".strip()


def _axis_label_translation_needs_retry(source_text: str, translated_text: str) -> bool:
    source_body, _source_unit = _split_axis_label_body_and_unit(source_text)
    if source_body is None:
        return False
    translated_body, _translated_unit = _split_axis_label_body_and_unit(translated_text)
    if translated_body is None:
        translated_body = _normalize_plain_axis_label_text(translated_text)
    if translated_body is None:
        return not str(translated_text or "").strip()
    return translated_body.casefold() == source_body.casefold()


def _retry_translate_axis_label_body_only(source_text: str, translation_config: Any) -> str | None:
    source_body, source_unit = _split_axis_label_body_and_unit(source_text)
    if source_body is None:
        return None
    protected_body, protected = _protect_technical_tokens_in_text(source_body)
    translated_body = translation_config.translator.translate(protected_body, ignore_cache=True)
    translated_body = _restore_protected_token_pairs(protected, translated_body)
    translated_body = _SPACE_COLLAPSE_RE.sub(" ", str(translated_body or "")).strip()
    if not translated_body:
        return None
    if source_unit:
        return f"{translated_body} ({source_unit})"
    return translated_body


def _split_axis_label_body_and_unit(text: str) -> tuple[str | None, str | None]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not normalized:
        return None, None
    unit_match = _TRAILING_UNIT_PARENS_RE.search(normalized)
    if unit_match is None:
        return _normalize_plain_axis_label_text(normalized), None
    body = normalized[: unit_match.start()].strip()
    unit = unit_match.group(1).strip()
    return _normalize_plain_axis_label_text(body), unit or None


def _restore_micro_unit_from_glyph_fonts(source_text: str, group: list[Any]) -> str:
    match = re.fullmatch(r"(?P<body>.+?)\s*\((?P<unit>m[A-Z])\)\s*", str(source_text or "").strip())
    if match is None:
        return source_text
    chars = _sorted_axis_chars(group)
    if len(chars) < 4:
        return source_text
    open_paren, prefix_char, suffix_char, close_paren = chars[-4:]
    raw_unit = "".join(str(getattr(char, "char_unicode", "") or "") for char in (open_paren, prefix_char, suffix_char, close_paren))
    if raw_unit not in {f"({match.group('unit')})", f"（{match.group('unit')}）"}:
        return source_text
    prefix_font = getattr(getattr(prefix_char, "pdf_style", None), "font_id", None)
    suffix_font = getattr(getattr(suffix_char, "pdf_style", None), "font_id", None)
    open_font = getattr(getattr(open_paren, "pdf_style", None), "font_id", None)
    close_font = getattr(getattr(close_paren, "pdf_style", None), "font_id", None)
    if prefix_font in {None, suffix_font}:
        return source_text
    if prefix_font in {open_font, close_font}:
        return source_text
    corrected_unit = f"u{match.group('unit')[1:]}"
    body = _SPACE_COLLAPSE_RE.sub(" ", match.group("body")).strip()
    return f"{body} ({corrected_unit})"

def _build_synthetic_axis_label_paragraph(
    il_version_1: Any,
    group: list[Any],
    source_text: str,
    source_rect: tuple[float, float, float, float],
) -> Any:
    if not group:
        return None
    first = group[0]
    style = copy.deepcopy(getattr(first, "pdf_style", None))
    if style is None or getattr(style, "font_id", None) is None or getattr(style, "font_size", None) is None:
        return None
    x1, y1, x2, y2 = source_rect
    label_height = max(x2 - x1, style.font_size * 1.8, 12.0)
    label_width = max(y2 - y1, style.font_size * max(len(source_text) * 0.8, 8.0))
    box = il_version_1.Box(
        x=x1,
        y=y1,
        x2=x1 + label_width,
        y2=y1 + label_height,
    )
    render_order = min(getattr(char, "render_order", 100) or 100 for char in group)
    return il_version_1.PdfParagraph(
        first_line_indent=False,
        box=box,
        vertical=False,
        pdf_style=style,
        unicode=source_text,
        pdf_paragraph_composition=[
            il_version_1.PdfParagraphComposition(
                pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
                    unicode=source_text,
                    pdf_style=style,
                ),
            ),
        ],
        xobj_id=getattr(first, "xobj_id", None),
        debug_id=f"synthetic-axis-{hashlib.sha1(source_text.encode('utf-8')).hexdigest()[:10]}",
        layout_label="axis_label",
        render_order=render_order,
    )


def _build_typesetting_fonts(page: Any, typesetter: Any) -> dict[str | int, Any]:
    fonts: dict[str | int, Any] = {f.font_id: f for f in getattr(page, "pdf_font", []) or [] if getattr(f, "font_id", None)}
    page_fonts = fonts.copy()
    for font_id, font in typesetter.font_mapper.fontid2font.items():
        fonts[font_id] = font
    for xobj in getattr(page, "pdf_xobject", []) or []:
        xobj_id = getattr(xobj, "xobj_id", None)
        if xobj_id is None:
            continue
        fonts[xobj_id] = page_fonts.copy()
        for font in getattr(xobj, "pdf_font", []) or []:
            if getattr(font, "font_id", None):
                fonts[xobj_id][font.font_id] = font
    return fonts


def _paragraph_pdf_chars(paragraph: Any) -> list[Any]:
    chars = []
    for composition in getattr(paragraph, "pdf_paragraph_composition", []) or []:
        same_style = getattr(composition, "pdf_same_style_characters", None)
        if same_style is not None:
            chars.extend(getattr(same_style, "pdf_character", []) or [])
        char = getattr(composition, "pdf_character", None)
        if char is not None:
            chars.append(char)
        formula = getattr(composition, "pdf_formula", None)
        if formula is not None:
            chars.extend(getattr(formula, "pdf_character", []) or [])
    return chars


def _composition_debug_payload(composition: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for index, item in enumerate(composition):
        entry: dict[str, Any] = {"index": index}
        same_style_chars = getattr(item, "pdf_same_style_characters", None)
        if same_style_chars is not None:
            chars = list(getattr(same_style_chars, "pdf_character", []) or [])
            style = getattr(same_style_chars, "pdf_style", None)
            entry.update(
                {
                    "kind": "same_style_characters",
                    "unicode": _characters_text(chars),
                    "font_id": getattr(style, "font_id", None),
                    "font_size": getattr(style, "font_size", None),
                    "char_count": len(chars),
                    "rect": _box_rect(getattr(same_style_chars, "box", None)),
                }
            )
            payload.append(entry)
            continue
        same_style = getattr(item, "pdf_same_style_unicode_characters", None)
        if same_style is not None:
            style = getattr(same_style, "pdf_style", None)
            entry.update(
                {
                    "kind": "same_style_unicode",
                    "unicode": str(getattr(same_style, "unicode", "") or ""),
                    "font_id": getattr(style, "font_id", None),
                    "font_size": getattr(style, "font_size", None),
                }
            )
            payload.append(entry)
            continue
        char = getattr(item, "pdf_character", None)
        if char is not None:
            style = getattr(char, "pdf_style", None)
            entry.update(
                {
                    "kind": "character",
                    "unicode": str(getattr(char, "char_unicode", "") or ""),
                    "font_id": getattr(style, "font_id", None),
                    "font_size": getattr(style, "font_size", None),
                    "pdf_character_id": getattr(char, "pdf_character_id", None),
                }
            )
            payload.append(entry)
            continue
        formula = getattr(item, "pdf_formula", None)
        if formula is not None:
            formula_chars = getattr(formula, "pdf_character", []) or []
            entry.update(
                {
                    "kind": "formula",
                    "unicode": "".join(str(getattr(char, "char_unicode", "") or "") for char in formula_chars),
                    "char_count": len(formula_chars),
                }
            )
            payload.append(entry)
            continue
        entry["kind"] = "unknown"
        payload.append(entry)
    return payload


def _axis_paragraph_diagnostics(records: list[_ParagraphRecord]) -> list[dict[str, Any]]:
    diagnostics = []
    for record in records:
        reasons = _axis_paragraph_reasons(record)
        if not reasons:
            continue
        width = None
        height = None
        if record.rect is not None:
            x1, y1, x2, y2 = record.rect
            width = round(x2 - x1, 3)
            height = round(y2 - y1, 3)
        diagnostics.append(
            {
                "paragraph_id": record.paragraph_id,
                "page_number": record.page_number,
                "paragraph_index": record.paragraph_index,
                "role": record.role,
                "policy": record.policy,
                "vertical": record.vertical,
                "layout_label": record.layout_label,
                "text": record.text,
                "rect": record.rect,
                "width": width,
                "height": height,
                "line_count": len([line for line in record.text.splitlines() if line.strip()]),
                "reasons": reasons,
            }
        )
        if len(diagnostics) >= 160:
            break
    return diagnostics


def _axis_paragraph_reasons(record: _ParagraphRecord) -> list[str]:
    reasons = []
    if record.vertical:
        reasons.append("babeldoc_vertical_flag")
    if _looks_like_axis_label_fragment(record.text):
        reasons.append("axis_label_fragment_text")
    if _looks_like_vertical_axis_text(record.text):
        reasons.append("vertical_axis_text")
    if _looks_like_horizontal_axis_label(record.text):
        reasons.append("horizontal_axis_label_text")
    if record.rect is not None:
        x1, y1, x2, y2 = record.rect
        width = x2 - x1
        height = y2 - y1
        if height > max(width * 2.2, 20):
            reasons.append("high_narrow_rect")
        elif height > width * 1.3 and _looks_like_vertical_axis_text(record.text):
            reasons.append("tall_multiline_axis_text")
    return reasons


def _looks_like_horizontal_axis_label(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not 3 <= len(normalized) <= 80:
        return False
    if "\n" in normalized:
        return False
    if not any(char.isalpha() for char in normalized):
        return False
    return _looks_like_axis_measurement_label(normalized)


def _page_level_axis_label_groups(chars: list[Any]) -> list[list[Any]]:
    items: list[tuple[Any, tuple[float, float, float, float], str]] = []
    for char in chars:
        text = str(getattr(char, "char_unicode", "") or "")
        if not text.strip() or text == "\n":
            continue
        rect = _box_rect(getattr(char, "box", None))
        if rect is None:
            continue
        x1, y1, x2, y2 = rect
        if x2 <= x1 or y2 <= y1:
            continue
        items.append((char, rect, text))

    items.sort(key=lambda item: ((_rect_center_x(item[1])), item[1][1]))
    columns: list[list[tuple[Any, tuple[float, float, float, float], str]]] = []
    current: list[tuple[Any, tuple[float, float, float, float], str]] = []
    current_x: float | None = None
    for item in items:
        center_x = _rect_center_x(item[1])
        if current and current_x is not None and abs(center_x - current_x) > 4.5:
            columns.append(current)
            current = []
            current_x = None
        current.append(item)
        current_x = center_x if current_x is None else (current_x * (len(current) - 1) + center_x) / len(current)
    if current:
        columns.append(current)

    groups: list[list[Any]] = []
    for column in columns:
        segment: list[tuple[Any, tuple[float, float, float, float], str]] = []
        previous_y2: float | None = None
        for item in sorted(column, key=lambda value: value[1][1]):
            y1 = item[1][1]
            if segment and previous_y2 is not None and y1 - previous_y2 > 8:
                if _is_page_level_axis_label_segment(segment):
                    groups.append([entry[0] for entry in segment])
                segment = []
            segment.append(item)
            previous_y2 = item[1][3]
        if segment and _is_page_level_axis_label_segment(segment):
            groups.append([entry[0] for entry in segment])
    return groups


def _is_page_level_axis_label_segment(segment: list[tuple[Any, tuple[float, float, float, float], str]]) -> bool:
    if len(segment) < 5:
        return False
    rect = _item_group_rect(segment)
    if rect is None:
        return False
    x1, y1, x2, y2 = rect
    width = x2 - x1
    height = y2 - y1
    if width > 24 or height < max(width * 2.5, 18):
        return False
    text = "".join(item[2] for item in sorted(segment, key=lambda value: value[1][1]))
    stripped = unicodedata.normalize("NFKC", text).strip()
    if _NUMERIC_OR_SYMBOL_RE.fullmatch(stripped):
        return False
    visible_chars = [char for char in stripped if not char.isspace()]
    letters = sum(1 for char in visible_chars if char.isalpha())
    if letters < 4:
        return False
    if _looks_like_repeated_table_noise_text(stripped):
        return False
    if _looks_like_tabular_vertical_column(segment):
        return False
    if _looks_like_tabular_tail_fragment(segment):
        return False
    if _looks_like_mixed_font_table_noise(segment, stripped):
        return False
    return _looks_like_axis_label_segment_text(stripped)


def _looks_like_axis_measurement_label(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    normalized = _SPACE_COLLAPSE_RE.sub(" ", normalized)
    return bool(_AXIS_LABEL_TEXT_RE.fullmatch(normalized))


def _looks_like_repeated_table_noise_text(text: str) -> bool:
    compact = _SPACE_COLLAPSE_RE.sub("", unicodedata.normalize("NFKC", str(text or "")).strip())
    if len(compact) < 10:
        return False
    alpha_only = "".join(char for char in compact if char.isalpha())
    if len(alpha_only) < 10:
        return False
    for tail_length in range(0, min(4, len(alpha_only) - 1) + 1):
        body = alpha_only[:-tail_length] if tail_length else alpha_only
        if len(body) < 8 or not body.isupper():
            continue
        for block_size in range(2, 5):
            repeats, remainder = divmod(len(body), block_size)
            if remainder or repeats < 3:
                continue
            block = body[:block_size]
            if body == block * repeats:
                return True
    return False


def _looks_like_tabular_vertical_column(segment: list[tuple[Any, tuple[float, float, float, float], str]]) -> bool:
    row_sizes = []
    current_y: float | None = None
    current_count = 0
    for _item, rect, _text in sorted(segment, key=lambda value: value[1][1]):
        y1 = rect[1]
        if current_y is None or abs(y1 - current_y) > 1.2:
            if current_count:
                row_sizes.append(current_count)
            current_y = y1
            current_count = 1
            continue
        current_count += 1
    if current_count:
        row_sizes.append(current_count)
    duplicated_rows = [size for size in row_sizes if size > 1]
    if not duplicated_rows:
        return False
    duplicated_chars = sum(duplicated_rows)
    return duplicated_chars >= max(4, len(segment) // 3)


def _looks_like_tabular_tail_fragment(segment: list[tuple[Any, tuple[float, float, float, float], str]]) -> bool:
    ordered = sorted(segment, key=lambda value: value[1][1])
    if len(ordered) < 5:
        return False
    centers_x = [_rect_center_x(rect) for _item, rect, _text in ordered]
    if max(centers_x) - min(centers_x) > 3.2:
        return False
    widths = [rect[2] - rect[0] for _item, rect, _text in ordered]
    if max(widths, default=0.0) > 8.0:
        return False
    row_gaps = [ordered[index + 1][1][1] - ordered[index][1][3] for index in range(len(ordered) - 1)]
    if not row_gaps:
        return False
    positive_gaps = [gap for gap in row_gaps if gap > 0]
    if len(positive_gaps) < len(row_gaps) - 1:
        return False
    median_gap = sorted(positive_gaps)[len(positive_gaps) // 2]
    if median_gap < 2.0:
        return False
    texts = [text.strip() for _item, _rect, text in ordered if text.strip()]
    if len(texts) < 4:
        return False
    short_tokens = sum(1 for text in texts if len(text) <= 2)
    if short_tokens < max(3, len(texts) - 1):
        return False
    return True


def _looks_like_mixed_font_table_noise(
    segment: list[tuple[Any, tuple[float, float, float, float], str]],
    stripped_text: str,
) -> bool:
    normalized = unicodedata.normalize("NFKC", str(stripped_text or "")).strip()
    compact = _SPACE_COLLAPSE_RE.sub("", normalized)
    if len(compact) < 6:
        return False
    if _looks_like_axis_measurement_label(normalized):
        return False
    if _normalize_plain_axis_label_text(normalized) is not None:
        return False
    font_ids = {
        getattr(getattr(item, "pdf_style", None), "font_id", None)
        for item, _rect, _text in segment
        if getattr(getattr(item, "pdf_style", None), "font_id", None) is not None
    }
    if len(font_ids) < 2:
        return False
    transitions = sum(
        1
        for left, right in zip(compact, compact[1:])
        if (left.islower() and right.isupper()) or (left.isalpha() and right.isdigit()) or (left.isdigit() and right.isalpha())
    )
    if transitions < 1:
        return False
    widths = [rect[2] - rect[0] for _item, rect, _text in segment]
    if max(widths, default=0.0) > 6.5:
        return False
    return True


def _looks_like_table_column_group(group: list[Any]) -> bool:
    items: list[tuple[Any, tuple[float, float, float, float], str]] = []
    for char in group:
        rect = _box_rect(getattr(char, "box", None))
        text = str(getattr(char, "char_unicode", "") or "")
        if rect is None or not text.strip():
            continue
        items.append((char, rect, text))
    if len(items) < 5:
        return False
    if not _looks_like_tabular_tail_fragment(items):
        return False
    texts = [text.strip() for _char, _rect, text in items if text.strip()]
    alpha_only = sum(1 for text in texts if re.fullmatch(r"[A-Za-z]{1,3}", text))
    return alpha_only >= max(4, len(texts) - 1)


def _looks_like_repeated_short_record_column(
    source_rect: tuple[float, float, float, float] | None,
    records: list[_ParagraphRecord],
) -> bool:
    if source_rect is None:
        return False
    matched: list[_ParagraphRecord] = []
    for record in records:
        if record.rect is None or not _rect_crosses_record_column(source_rect, record.rect):
            continue
        text = unicodedata.normalize("NFKC", str(record.text or "")).strip()
        compact = _SPACE_COLLAPSE_RE.sub("", text)
        if not compact or len(compact) > 6:
            continue
        if not re.fullmatch(r"[A-Z0-9]{2,6}", compact):
            continue
        matched.append(record)
    if len(matched) < 4:
        return False
    canonical_counts: dict[str, int] = {}
    for record in matched:
        canonical_counts[record.canonical_text] = canonical_counts.get(record.canonical_text, 0) + 1
    return max(canonical_counts.values(), default=0) >= 4


def _group_overlaps_preserved_short_records(
    source_rect: tuple[float, float, float, float],
    records: list[_ParagraphRecord],
) -> bool:
    matched = 0
    preserved = 0
    for record in records:
        if record.rect is None or not _rect_crosses_record_column(source_rect, record.rect):
            continue
        matched += 1
        compact = _SPACE_COLLAPSE_RE.sub("", unicodedata.normalize("NFKC", str(record.text or "")).strip())
        if record.policy == "preserve" and compact and len(compact) <= 8:
            preserved += 1
    return preserved >= 4 and preserved >= max(4, matched - 1)


def _looks_like_axis_label_segment_text(text: str) -> bool:
    for normalized in _axis_label_text_variants(text):
        compact = _SPACE_COLLAPSE_RE.sub("", normalized)
        if _looks_like_axis_measurement_label(normalized):
            return True
        if _normalize_plain_axis_label_text(normalized) is not None:
            return True
        if not 4 <= len(compact) <= 80:
            continue
        if not any(char.isalpha() or "\u4e00" <= char <= "\u9fff" for char in compact):
            continue
        if re.search(r"(?:µA|uA|mA|µV|uV|mV|dB|LSB|%)", compact):
            digits = sum(char.isdigit() for char in compact)
            if digits <= max(3, len(compact) // 3):
                return True
    return False


def _char_group_text(group: list[Any]) -> str:
    items = []
    for char in group:
        rect = _box_rect(getattr(char, "box", None))
        if rect is None:
            continue
        items.append((rect, str(getattr(char, "char_unicode", "") or "")))
    return "".join(text for _rect, text in sorted(items, key=lambda item: item[0][1]))


def _char_group_rect(group: list[Any]) -> tuple[float, float, float, float] | None:
    rects = [_box_rect(getattr(char, "box", None)) for char in group]
    return _rect_union([rect for rect in rects if rect is not None])


def _item_group_rect(items: list[tuple[Any, tuple[float, float, float, float], str]]) -> tuple[float, float, float, float] | None:
    return _rect_union([item[1] for item in items])


def _rect_union(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    if not rects:
        return None
    return (
        round(min(rect[0] for rect in rects), 3),
        round(min(rect[1] for rect in rects), 3),
        round(max(rect[2] for rect in rects), 3),
        round(max(rect[3] for rect in rects), 3),
    )


def _rect_overlap_ratio(
    left: tuple[float, float, float, float] | None,
    right: tuple[float, float, float, float] | None,
) -> float:
    if left is None or right is None:
        return 0.0
    overlap_x = min(left[2], right[2]) - max(left[0], right[0])
    overlap_y = min(left[3], right[3]) - max(left[1], right[1])
    if overlap_x <= 0 or overlap_y <= 0:
        return 0.0
    overlap_area = overlap_x * overlap_y
    left_area = max((left[2] - left[0]) * (left[3] - left[1]), 1e-6)
    return overlap_area / left_area


def _best_point_aligned_record(
    char_rect: tuple[float, float, float, float],
    records: list[_ParagraphRecord],
) -> _ParagraphRecord | None:
    center_x = (char_rect[0] + char_rect[2]) / 2
    center_y = (char_rect[1] + char_rect[3]) / 2
    best: tuple[tuple[float, float], _ParagraphRecord] | None = None
    for record in records:
        rect = record.rect
        if rect is None or not _rect_contains_point(rect, center_x, center_y, padding=0.8):
            continue
        score = (abs(_rect_center_x(rect) - center_x), abs(((rect[1] + rect[3]) / 2) - center_y))
        if best is None or score < best[0]:
            best = (score, record)
    return None if best is None else best[1]


def _looks_like_record_aligned_table_column(
    source_rect: tuple[float, float, float, float],
    records: list[_ParagraphRecord],
) -> bool:
    matched_non_axis = 0
    matched_axis = 0
    for record in records:
        rect = record.rect
        if rect is None or not _rect_crosses_record_column(source_rect, rect):
            continue
        if (
            record.role == "vertical_label"
            or _looks_like_axis_label_fragment(record.text)
            or _looks_like_horizontal_axis_label(record.text)
        ):
            matched_axis += 1
            continue
        matched_non_axis += 1
    return matched_axis == 0 and matched_non_axis >= 4


def _rect_crosses_record_column(
    column_rect: tuple[float, float, float, float],
    record_rect: tuple[float, float, float, float],
) -> bool:
    record_center_x = _rect_center_x(record_rect)
    if record_center_x < column_rect[0] - 3.5 or record_center_x > column_rect[2] + 3.5:
        return False
    overlap_y = min(column_rect[3], record_rect[3]) - max(column_rect[1], record_rect[1])
    if overlap_y <= 0:
        return False
    record_height = max(record_rect[3] - record_rect[1], 1.0)
    return overlap_y / record_height >= 0.45


def _rect_contains_point(
    rect: tuple[float, float, float, float],
    x: float,
    y: float,
    *,
    padding: float = 0.0,
) -> bool:
    return rect[0] - padding <= x <= rect[2] + padding and rect[1] - padding <= y <= rect[3] + padding


def _rect_center_x(rect: tuple[float, float, float, float]) -> float:
    return (rect[0] + rect[2]) / 2


def _is_vertical_candidate(record: _ParagraphRecord) -> bool:
    if record.vertical:
        return True
    if _looks_like_axis_label_fragment(record.text):
        return True
    if record.rect is None:
        return False
    x1, y1, x2, y2 = record.rect
    width = x2 - x1
    height = y2 - y1
    return height > max(width * 2.2, 20) or (height > width * 1.3 and _looks_like_vertical_axis_text(record.text))


def _detect_vertical_label_fragment_ids(records: list[_ParagraphRecord]) -> set[str]:
    grouped: dict[tuple[int | None, int | str | None], list[_ParagraphRecord]] = {}
    for record in records:
        if not _is_vertical_fragment_record(record):
            continue
        grouped.setdefault((record.page_number, record.xobj_id), []).append(record)

    matched_ids: set[str] = set()
    for group_records in grouped.values():
        segments = _vertical_fragment_segments(group_records)
        numeric_segments = [segment for segment in segments if _is_vertical_numeric_segment(segment)]
        if not numeric_segments:
            continue
        for segment in segments:
            if not _is_vertical_label_fragment_segment(segment):
                continue
            if not _has_adjacent_vertical_numeric_segment(segment, numeric_segments):
                continue
            matched_ids.update(record.paragraph_id for record in segment)
    return matched_ids


def _is_vertical_fragment_record(record: _ParagraphRecord) -> bool:
    rect = record.rect
    if rect is None:
        return False
    compact = _compact_vertical_fragment_text(record.text)
    if not compact or len(compact) > 4:
        return False
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    max_width = 15.0 if _is_vertical_numeric_fragment_text(compact) else 12.0
    return width <= max_width and height <= 10.5


def _compact_vertical_fragment_text(text: str) -> str:
    return _SPACE_COLLAPSE_RE.sub("", unicodedata.normalize("NFKC", str(text or "")).strip())


def _vertical_fragment_segments(records: list[_ParagraphRecord]) -> list[list[_ParagraphRecord]]:
    ordered = sorted(records, key=lambda record: (_rect_center_x(record.rect), record.rect[1]) if record.rect is not None else (math.inf, math.inf))
    columns: list[list[_ParagraphRecord]] = []
    current: list[_ParagraphRecord] = []
    current_x: float | None = None
    for record in ordered:
        rect = record.rect
        if rect is None:
            continue
        center_x = _rect_center_x(rect)
        if current and current_x is not None and abs(center_x - current_x) > 7.0:
            columns.append(current)
            current = []
            current_x = None
        current.append(record)
        current_x = center_x if current_x is None else ((current_x * (len(current) - 1)) + center_x) / len(current)
    if current:
        columns.append(current)

    segments: list[list[_ParagraphRecord]] = []
    for column in columns:
        segment: list[_ParagraphRecord] = []
        previous_y2: float | None = None
        for record in sorted(column, key=lambda candidate: candidate.rect[1] if candidate.rect is not None else math.inf):
            rect = record.rect
            if rect is None:
                continue
            if segment and previous_y2 is not None and rect[1] - previous_y2 > 24.0:
                segments.append(segment)
                segment = []
            segment.append(record)
            previous_y2 = rect[3]
        if segment:
            segments.append(segment)
    return segments


def _is_vertical_numeric_segment(segment: list[_ParagraphRecord]) -> bool:
    if len(segment) < 4:
        return False
    numericish = sum(1 for record in segment if _is_vertical_numeric_fragment_text(record.text))
    return numericish >= math.ceil(len(segment) * 0.6)


def _is_vertical_numeric_fragment_text(text: str) -> bool:
    compact = _compact_vertical_fragment_text(text)
    if not compact:
        return False
    if compact in {"-", ".", "±"}:
        return True
    return re.fullmatch(r"[-+]?\d+(?:\.\d+)?-?", compact) is not None


def _is_vertical_label_fragment_segment(segment: list[_ParagraphRecord]) -> bool:
    if len(segment) < 4:
        return False
    rect = _records_rect(segment)
    if rect is None:
        return False
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    if width > 18.0 or height < 20.0:
        return False
    texts = [_compact_vertical_fragment_text(record.text) for record in segment]
    joined = "".join(texts)
    if not any(char.islower() for char in joined):
        return False
    labelish = sum(1 for text in texts if any(char.isalpha() for char in text) or text in {"(", ")", "%"})
    return labelish >= 4


def _has_adjacent_vertical_numeric_segment(
    label_segment: list[_ParagraphRecord],
    numeric_segments: list[list[_ParagraphRecord]],
) -> bool:
    label_rect = _records_rect(label_segment)
    if label_rect is None:
        return False
    label_center_x = _rect_center_x(label_rect)
    label_height = label_rect[3] - label_rect[1]
    for segment in numeric_segments:
        numeric_rect = _records_rect(segment)
        if numeric_rect is None:
            continue
        dx = _rect_center_x(numeric_rect) - label_center_x
        if dx < 8.0 or dx > 35.0:
            continue
        overlap = min(label_rect[3], numeric_rect[3]) - max(label_rect[1], numeric_rect[1])
        numeric_height = numeric_rect[3] - numeric_rect[1]
        if overlap >= min(label_height, numeric_height) * 0.5:
            return True
    return False


def _records_rect(records: list[_ParagraphRecord]) -> tuple[float, float, float, float] | None:
    rects = [record.rect for record in records if record.rect is not None]
    if not rects:
        return None
    return (
        min(rect[0] for rect in rects),
        min(rect[1] for rect in rects),
        max(rect[2] for rect in rects),
        max(rect[3] for rect in rects),
    )


def _is_toc_candidate(record: _ParagraphRecord, total_pages: int) -> bool:
    if record.page_index > max(4, int(total_pages * 0.15)):
        return False
    text = unicodedata.normalize("NFKC", record.text).strip()
    if len(text) > 240:
        return False
    return bool(_DOT_LEADER_TOC_RE.search(text))


def _split_toc_entry(text: str) -> tuple[str, str, str] | None:
    match = _TOC_ENTRY_RE.match(unicodedata.normalize("NFKC", text).strip())
    if match is None:
        return None
    title = match.group("title").strip()
    leader = match.group("leader")
    page_number = match.group("page")
    if not title:
        return None
    return title, leader, page_number


def _normalize_toc_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).strip()
    return _ACRONYM_BOUNDARY_RE.sub(" ", _CAMEL_BOUNDARY_RE.sub(" ", normalized))


def _clean_toc_title_translation(translated_text: str, source_title: str) -> str:
    cleaned = unicodedata.normalize("NFKC", translated_text).strip()
    cleaned = _TRAILING_TOC_LOCATOR_RE.sub("", cleaned).strip()
    return cleaned or _normalize_toc_title(source_title)


def _compose_toc_entry(
    source_title: str,
    source_leader: str,
    translated_title: str,
    page_number: str,
    anchor_width: int | None = None,
) -> str:
    source_prefix_width = anchor_width or _display_width(f"{source_title}{source_leader}")
    leader_width = max(source_prefix_width - _display_width(translated_title), 4)
    return f"{translated_title}{'.' * leader_width} {page_number}"


def _display_width(text: str) -> int:
    width = 0
    for char in text:
        if char.isspace():
            width += 1
        elif unicodedata.east_asian_width(char) in {"F", "W"}:
            width += 2
        else:
            width += 1
    return width


def _toc_column_key(record: _ParagraphRecord) -> str:
    if record.rect is None or record.page_rect is None:
        return "unknown"
    x1, _y1, x2, _y2 = record.rect
    px1, _py1, px2, _py2 = record.page_rect
    page_center = px1 + (px2 - px1) / 2
    block_center = x1 + (x2 - x1) / 2
    if x1 <= page_center <= x2:
        return "full"
    return "left" if block_center < page_center else "right"


def _restore_source_line_breaks(source_text: str, translated_text: str) -> str:
    if _has_inline_numbered_markers(source_text):
        return _restore_numbered_marker_breaks(translated_text)

    if "\n" not in source_text:
        return translated_text

    source_lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    if len(source_lines) < 2:
        return translated_text

    numbered_source_lines = sum(1 for line in source_lines if _NUMBERED_LINE_START_RE.match(line))
    if numbered_source_lines >= 2:
        return _restore_numbered_marker_breaks(translated_text)

    if "\n" in translated_text:
        return translated_text

    first_line = source_lines[0]
    if translated_text.startswith(first_line) and len(translated_text) > len(first_line):
        return f"{first_line}\n{translated_text[len(first_line):].lstrip()}"

    return translated_text


def _has_inline_numbered_markers(source_text: str) -> bool:
    markers = list(_NUMBERED_MARKER_RE.finditer(source_text))
    return len(markers) >= 2 and markers[0].start() <= 2


def _split_marketing_status_line(text: str) -> tuple[str, str] | None:
    match = _MARKETING_STATUS_LINE_RE.match(str(text or ""))
    if match is None:
        return None
    key = match.group(1).upper()
    label = _MARKETING_STATUS_TRANSLATIONS.get(key)
    body = match.group(2).strip()
    if label is None or not body:
        return None
    return label, body


def _restore_numbered_marker_breaks(translated_text: str) -> str:
    marker_pattern = re.compile(r"\s*((?:\(\d{1,3}\)\s*|(?<!\()\d{1,3}[.)]\s+))")

    def restore_marker(match: re.Match[str]) -> str:
        marker = match.group(1)
        return marker if match.start() == 0 else f"\n{marker}"

    return marker_pattern.sub(restore_marker, translated_text.strip())


def _strip_babeldoc_style_placeholders(text: str) -> str:
    return _BABELDOC_STYLE_PLACEHOLDER_RE.sub("", text)


def _restore_definition_line_styles_from_source(paragraph: Any, source_composition: list[Any]) -> bool:
    translated_text = str(getattr(paragraph, "unicode", "") or "")
    if not translated_text:
        return False
    current_composition = list(getattr(paragraph, "pdf_paragraph_composition", []) or [])
    if len(current_composition) != 1:
        return False
    current_run = getattr(current_composition[0], "pdf_same_style_unicode_characters", None)
    if current_run is None:
        return False
    source_runs = _definition_line_style_runs(source_composition)
    if source_runs is None:
        return False
    prefix_text, body_text = _split_definition_line_translation(translated_text)
    if not prefix_text or not body_text:
        return False

    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
    from babeldoc.format.pdf.document_il.il_version_1 import PdfSameStyleUnicodeCharacters

    prefix_style, body_style = source_runs
    rebuilt: list[Any] = []
    prefix_comp = PdfParagraphComposition()
    prefix_comp.pdf_same_style_unicode_characters = PdfSameStyleUnicodeCharacters(
        pdf_style=copy.deepcopy(prefix_style),
        unicode=prefix_text,
    )
    rebuilt.append(prefix_comp)

    body_comp = PdfParagraphComposition()
    body_comp.pdf_same_style_unicode_characters = PdfSameStyleUnicodeCharacters(
        pdf_style=copy.deepcopy(body_style),
        unicode=body_text,
    )
    rebuilt.append(body_comp)
    paragraph.pdf_paragraph_composition = rebuilt
    paragraph.unicode = f"{prefix_text}{body_text}"
    return True


def _definition_line_style_runs(source_composition: list[Any]) -> tuple[Any, Any] | None:
    runs: list[tuple[str, Any]] = []
    for item in source_composition:
        same_style = getattr(item, "pdf_same_style_characters", None)
        if same_style is not None:
            text = _characters_text(list(getattr(same_style, "pdf_character", []) or []))
            style = getattr(same_style, "pdf_style", None)
        else:
            same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
            if same_style_unicode is None:
                return None
            text = str(getattr(same_style_unicode, "unicode", "") or "")
            style = getattr(same_style_unicode, "pdf_style", None)
        if not text or style is None:
            continue
        runs.append((text, style))
    if len(runs) < 2:
        return None
    prefix_text = runs[0][0]
    if re.search(r"[:：]\s*$", prefix_text) is None:
        return None
    prefix_style = runs[0][1]
    body_style = runs[1][1]
    if _same_style_identity(prefix_style, body_style):
        return None
    if any(not _same_style_identity(style, body_style) for _text, style in runs[1:]):
        return None
    return prefix_style, body_style


def _same_style_identity(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return (
        getattr(left, "font_id", None),
        getattr(left, "font_size", None),
    ) == (
        getattr(right, "font_id", None),
        getattr(right, "font_size", None),
    )


def _split_definition_line_translation(text: str) -> tuple[str, str] | tuple[None, None]:
    value = str(text or "").strip()
    if not value:
        return None, None
    match = re.search(r"[:：]", value)
    if match is None:
        return None, None
    prefix = value[: match.end()].strip()
    body = value[match.end() :].strip()
    if not prefix or not body:
        return None, None
    return prefix, body


def _split_paragraph_by_lines(paragraph: Any, lines: list[str]) -> list[Any]:
    from babeldoc.format.pdf.document_il.il_version_1 import Box
    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
    from babeldoc.format.pdf.document_il.il_version_1 import PdfSameStyleUnicodeCharacters

    original_box = getattr(paragraph, "box", None)
    if original_box is None:
        return [paragraph]
    x1, y1, x2, y2 = (
        getattr(original_box, "x", None),
        getattr(original_box, "y", None),
        getattr(original_box, "x2", None),
        getattr(original_box, "y2", None),
    )
    if any(value is None for value in (x1, y1, x2, y2)) or y2 <= y1:
        return [paragraph]

    weights = [max(1, math.ceil(_display_width(line) / 90)) for line in lines]
    total_weight = sum(weights)
    total_height = y2 - y1
    cursor_top = y2
    split_paragraphs = []
    for index, (line, weight) in enumerate(zip(lines, weights, strict=True)):
        height = total_height * weight / total_weight
        bottom = y1 if index == len(lines) - 1 else cursor_top - height
        split_paragraph = copy.deepcopy(paragraph)
        split_paragraph.box = Box(x=x1, y=bottom, x2=x2, y2=cursor_top)
        split_paragraph.unicode = line
        split_paragraph.optimal_scale = None
        if getattr(split_paragraph, "debug_id", None):
            split_paragraph.debug_id = f"{split_paragraph.debug_id}:line:{index + 1}"
        comp = PdfParagraphComposition()
        comp.pdf_same_style_unicode_characters = PdfSameStyleUnicodeCharacters(
            pdf_style=getattr(paragraph, "pdf_style", None),
            unicode=line,
        )
        split_paragraph.pdf_paragraph_composition = [comp]
        split_paragraphs.append(split_paragraph)
        cursor_top = bottom
    return split_paragraphs


def _set_plain_unicode_paragraph_text(paragraph: Any, text: str) -> None:
    from babeldoc.format.pdf.document_il.il_version_1 import Box
    from babeldoc.format.pdf.document_il.il_version_1 import PdfCharacter
    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
    from babeldoc.format.pdf.document_il.il_version_1 import PdfSameStyleCharacters
    from babeldoc.format.pdf.document_il.il_version_1 import PdfSameStyleUnicodeCharacters

    comp = PdfParagraphComposition()
    style = getattr(paragraph, "pdf_style", None)
    rect = _box_rect(getattr(paragraph, "box", None))
    if rect is not None and text:
        x1, y1, x2, y2 = rect
        advance = (x2 - x1) / max(len(text), 1)
        chars = []
        for index, char_text in enumerate(text):
            chars.append(
                PdfCharacter(
                    pdf_style=copy.deepcopy(style),
                    box=Box(
                        x=x1 + (advance * index),
                        y=y1,
                        x2=x1 + (advance * (index + 1)),
                        y2=y2,
                    ),
                    vertical=False,
                    char_unicode=char_text,
                    advance=advance,
                    xobj_id=getattr(paragraph, "xobj_id", None),
                    render_order=getattr(paragraph, "render_order", None),
                )
            )
        comp.pdf_same_style_characters = PdfSameStyleCharacters(
            box=Box(x=x1, y=y1, x2=x2, y2=y2),
            pdf_style=copy.deepcopy(style),
            pdf_character=chars,
        )
    else:
        comp.pdf_same_style_unicode_characters = PdfSameStyleUnicodeCharacters(
            pdf_style=style,
            unicode=text,
        )
    paragraph.pdf_paragraph_composition = [comp]
    paragraph.unicode = text


def _protect_technical_tokens_in_text(text: str) -> tuple[str, list[tuple[str, str]]]:
    replacements: list[tuple[int, int]] = []
    for pattern in (
        _TECHNICAL_COMPACT_EQUATION_RE,
        _PLACEHOLDER_BRIDGED_TECHNICAL_TOKEN_RE,
        _PLACEHOLDER_BRIDGED_DIMENSION_CHAIN_RE,
        _DIMENSION_CHAIN_RE,
        _TECHNICAL_RATIO_TOKEN_RE,
        _TECHNICAL_NUMBER_UNIT_RE,
        _TECHNICAL_COMPOUND_IDENTIFIER_RE,
        _TECHNICAL_IDENTIFIER_RE,
        _SINGLE_LETTER_TECHNICAL_RE,
        _TECHNICAL_UNIT_RE,
    ):
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < existing_end and end > existing_start for existing_start, existing_end in replacements):
                continue
            replacements.append((start, end))
    if not replacements:
        return text, []

    replacements.sort()
    pieces: list[str] = []
    protected: list[tuple[str, str]] = []
    cursor = 0
    for index, (start, end) in enumerate(replacements):
        token = text[start:end]
        placeholder = _protected_token_placeholder(token, index=index, start=start, end=end)
        pieces.append(text[cursor:start])
        pieces.append(placeholder)
        protected.append((placeholder, token))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), protected


def _protected_token_placeholder(token: str, *, index: int, start: int, end: int) -> str:
    digest = hashlib.sha1(f"{index}:{start}:{end}:{token}".encode("utf-8")).hexdigest()[:10].upper()
    return f"DTX{digest}Q"


def _restore_protected_token_pairs(protected: list[tuple[str, str]], translated_text: str) -> str:
    restored = translated_text
    for placeholder, token in protected:
        restored = re.sub(re.escape(placeholder), token, restored, flags=re.IGNORECASE)
    return restored


def _repair_translate_input_text(source_text: str, translated_input_text: str, translate_input: Any | None) -> str:
    source = str(source_text or "")
    current = str(translated_input_text or "")
    if not source or not current or source == current:
        return current or source
    if translate_input is None:
        return source

    repaired = source
    placeholders = list(getattr(translate_input, "placeholders", None) or [])
    if not placeholders:
        return repaired

    for placeholder in placeholders:
        placeholder_token = str(getattr(placeholder, "placeholder", "") or "")
        placeholder_type = str(getattr(placeholder, "type", "") or "")
        if not placeholder_token or placeholder_type != "formula":
            continue
        composition_chars = str(getattr(placeholder, "composition_chars", "") or "")
        formula_chars = str(getattr(placeholder, "formula_chars", "") or "")
        source_fragment = composition_chars or formula_chars
        if not source_fragment:
            continue
        numeric_bridge = _formula_numeric_bridge_fragment(source_fragment, repaired)
        if numeric_bridge is not None:
            repaired = repaired.replace(numeric_bridge, placeholder_token, 1)
            continue
        repaired = repaired.replace(source_fragment, placeholder_token, 1)
    return repaired


def _normalize_translation_input_text(
    paragraph: Any,
    source_text: str,
    translated_input_text: str,
    translate_input: Any | None,
    applied_events: list[dict[str, Any]],
    record: _ParagraphRecord,
) -> str:
    source = str(source_text or "")
    current = str(translated_input_text or "")
    if not source:
        return current
    rebuilt = _rebuild_translation_input_from_composition(paragraph)
    if rebuilt:
        rebuilt = _normalize_translation_input_connector_markers(rebuilt)
    candidate = current
    if _should_use_source_text_for_placeholder_mismatch(source, candidate):
        candidate = source
    if rebuilt and rebuilt != candidate and _should_prefer_composition_rebuilt_input(source, candidate, rebuilt):
        candidate = rebuilt
    if _has_formula_placeholders(translate_input):
        branch = "repair"
        if rebuilt and candidate == rebuilt:
            outgoing = rebuilt
            branch = "composition_rebuilt"
        elif candidate == source or _should_use_literal_source_text_for_formula_placeholders(source, translate_input):
            outgoing = source
            branch = "literal_source"
        else:
            outgoing = _repair_translate_input_text(source, candidate, translate_input)
        applied_events.append(
            {
                "action": "formula_placeholder_translation_input_override",
                "paragraph_id": record.paragraph_id,
                "layout_label": record.layout_label,
                "branch": branch,
                "incoming_text": str(getattr(translate_input, "unicode", "") or "")[:180],
                "source_text": source[:180],
                "outgoing_text": outgoing[:180],
            }
        )
        return outgoing

    if not rebuilt or rebuilt == candidate:
        return candidate
    if not _should_prefer_composition_rebuilt_input(source, candidate, rebuilt):
        return candidate
    applied_events.append(
        {
            "action": "composition_translation_input_override",
            "paragraph_id": record.paragraph_id,
            "layout_label": record.layout_label,
            "incoming_text": candidate[:180],
            "source_text": source[:180],
            "outgoing_text": rebuilt[:180],
        }
    )
    return rebuilt


def _should_use_literal_source_text_for_formula_placeholders(source_text: str, translate_input: Any | None) -> bool:
    if translate_input is None:
        return False
    source = str(source_text or "")
    if not source:
        return False
    for placeholder in getattr(translate_input, "placeholders", None) or []:
        if str(getattr(placeholder, "type", "") or "") != "formula":
            continue
        formula_chars = str(getattr(placeholder, "formula_chars", "") or "")
        composition_chars = str(getattr(placeholder, "composition_chars", "") or "")
        fragment = composition_chars or formula_chars
        normalized_fragment = unicodedata.normalize("NFKC", fragment).strip()
        if not normalized_fragment:
            continue
        if normalized_fragment == "_":
            return True
        if _formula_numeric_bridge_fragment(normalized_fragment, source) is not None:
            return True
        if re.fullmatch(r"[+\-±]\s*\d+(?:[.,]\d+)?", normalized_fragment):
            return True
        if re.fullmatch(r"[+\-±]\s*\d+", normalized_fragment):
            return True
    return False


def _has_formula_placeholders(translate_input: Any | None) -> bool:
    if translate_input is None:
        return False
    for placeholder in getattr(translate_input, "placeholders", None) or []:
        if str(getattr(placeholder, "type", "") or "") == "formula":
            return True
    return False


def _formula_numeric_bridge_fragment(source_fragment: str, source_text: str) -> str | None:
    fragment = str(source_fragment or "").strip()
    if not fragment:
        return None
    compact_fragment = re.sub(r"\s+", "", fragment)
    match = re.fullmatch(r"(?:=)?([+\-±]?\d+)", compact_fragment)
    if not match:
        return None
    numeric_head = match.group(1)
    source = str(source_text or "")
    candidate_patterns = (
        rf"=\s*{re.escape(numeric_head)}(?=[\.,]\d)",
        rf"(?<![A-Za-z0-9]){re.escape(numeric_head)}(?=[\.,]\d)",
        rf"{re.escape(numeric_head)}(?=[\.,]\d)",
    )
    for pattern in candidate_patterns:
        found = re.search(pattern, source)
        if found:
            return found.group(0)
    return None


def _should_prefer_composition_rebuilt_input(source_text: str, current_text: str, rebuilt_text: str) -> bool:
    source = str(source_text or "")
    current = str(current_text or "")
    rebuilt = str(rebuilt_text or "")
    if not rebuilt or rebuilt == current:
        return False
    anomaly_patterns = (
        r"(?<![A-Za-z])COMP(?:QUE|MODE)(?=\s+bit)",
        r"theConfigregister",
        r"bitscanalso",
        r"\btheCOMP\b",
        r"\bandCOMP\b",
    )
    if any(re.search(pattern, current) for pattern in anomaly_patterns):
        return True
    if source and any(re.search(pattern, source) for pattern in anomaly_patterns):
        return True
    return False


def _should_use_source_text_for_placeholder_mismatch(source_text: str, current_text: str) -> bool:
    source = str(source_text or "")
    current = str(current_text or "")
    if not source or not current:
        return False
    if _PLACEHOLDER_TOKEN_RE.search(current) is None:
        return False
    if _PLACEHOLDER_TOKEN_RE.search(source) is not None:
        return False
    if not re.search(r"[A-Za-z0-9]\s*\{[^{}\s]+\}|\{[^{}\s]+\}\s*[A-Za-z0-9]", current):
        return False
    if "_" in source:
        return True
    if re.search(r"[A-Za-z0-9]\s*[+\-±]\s*\d", source):
        return True
    if re.search(r"\d+[.,]\d+[A-Za-z%°ΩΩµμ]+", source):
        return True
    return False


def _rebuild_translation_input_from_composition(paragraph: Any) -> str | None:
    composition = list(getattr(paragraph, "pdf_paragraph_composition", []) or [])
    if not composition:
        return None
    parts: list[str] = []
    previous_item = None
    previous_previous_item = None
    for item in composition:
        current_text = _composition_item_text(item)
        if not current_text:
            previous_previous_item = previous_item
            previous_item = item
            continue
        if previous_item is not None:
            joiner = _translation_input_joiner_between_items(previous_previous_item, previous_item, item)
            if joiner:
                parts.append(joiner)
        parts.append(current_text)
        previous_previous_item = previous_item
        previous_item = item
    rebuilt = "".join(parts).strip()
    return rebuilt or None


def _composition_item_text(item: Any) -> str:
    same_style = getattr(item, "pdf_same_style_characters", None)
    if same_style is not None:
        return _characters_text(list(getattr(same_style, "pdf_character", []) or []))
    same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
    if same_style_unicode is not None:
        return str(getattr(same_style_unicode, "unicode", "") or "")
    formula = getattr(item, "pdf_formula", None)
    if formula is not None:
        return _characters_text(list(getattr(formula, "pdf_character", []) or []))
    char = getattr(item, "pdf_character", None)
    if char is not None:
        return str(getattr(char, "char_unicode", "") or "")
    line = getattr(item, "pdf_line", None)
    if line is not None:
        return str(getattr(line, "unicode", "") or "")
    return ""


def _translation_input_joiner_between_items(previous_previous_item: Any, previous_item: Any, current_item: Any) -> str:
    if _should_insert_technical_identifier_connector(previous_item, current_item):
        return "_"
    if _needs_implicit_space_between_items(previous_previous_item, previous_item, current_item):
        return " "
    return ""


def _needs_implicit_space_between_items(previous_previous_item: Any, previous_item: Any, current_item: Any) -> bool:
    previous_chars = _composition_boundary_chars(previous_item)
    current_chars = _composition_boundary_chars(current_item)
    if not previous_chars or not current_chars:
        return False
    previous_previous_chars = _composition_boundary_chars(previous_previous_item) if previous_previous_item is not None else None
    previous_previous_char = previous_previous_chars[-1] if previous_previous_chars else None
    previous_char = previous_chars[-1]
    current_char = current_chars[0]
    current_text = str(getattr(current_char, "char_unicode", "") or "")
    return _needs_implicit_space(previous_previous_char, previous_char, current_char, current_text)


def _should_insert_technical_identifier_connector(previous_item: Any, current_item: Any) -> bool:
    previous_text = _composition_item_text(previous_item).rstrip()
    current_text = _composition_item_text(current_item).lstrip()
    if not previous_text or not current_text:
        return False
    if previous_text.endswith("_") or current_text.startswith("_"):
        return False
    previous_match = re.search(r"([A-Z]{2,10})$", previous_text)
    current_match = re.match(r"([A-Z]{2,10})(?=\b|[^A-Za-z])", current_text)
    if previous_match is None or current_match is None:
        return False
    previous_rect = _composition_item_rect(previous_item)
    current_rect = _composition_item_rect(current_item)
    if previous_rect is None or current_rect is None:
        return False
    gap = current_rect[0] - previous_rect[2]
    if gap < -1.0:
        return False
    font_sizes = []
    for item in (previous_item, current_item):
        rect_chars = _composition_boundary_chars(item)
        for char in rect_chars[:1] + rect_chars[-1:]:
            style = getattr(char, "pdf_style", None)
            font_size = float(getattr(style, "font_size", 0) or 0)
            if font_size > 0:
                font_sizes.append(font_size)
    gap_limit = max(8.0, (min(font_sizes) * 0.85) if font_sizes else 8.0)
    if gap > gap_limit:
        return False
    return True


def _normalize_translation_input_connector_markers(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    normalized = re.sub(r"(?<![A-Za-z0-9])_+(?=[A-Za-z0-9])", "", normalized)
    normalized = re.sub(r"(?<=[A-Za-z0-9])_+(?![A-Za-z0-9])", "", normalized)
    normalized = re.sub(r"_+(?=[\s.,;:!?)]|$)", "", normalized)
    normalized = re.sub(r"(^|[\s(])_+", r"\1", normalized)
    return normalized


def _composition_boundary_chars(item: Any) -> list[Any]:
    if item is None:
        return []
    same_style = getattr(item, "pdf_same_style_characters", None)
    if same_style is not None:
        return [char for char in getattr(same_style, "pdf_character", []) or [] if str(getattr(char, "char_unicode", "") or "")]
    same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
    if same_style_unicode is not None:
        text = str(getattr(same_style_unicode, "unicode", "") or "")
        if not text:
            return []
        return _synthetic_boundary_chars_from_unicode(text, getattr(same_style_unicode, "box", None), getattr(same_style_unicode, "pdf_style", None))
    formula = getattr(item, "pdf_formula", None)
    if formula is not None:
        return [char for char in getattr(formula, "pdf_character", []) or [] if str(getattr(char, "char_unicode", "") or "")]
    char = getattr(item, "pdf_character", None)
    if char is not None and str(getattr(char, "char_unicode", "") or ""):
        return [char]
    return []


def _synthetic_boundary_chars_from_unicode(text: str, box: Any, style: Any) -> list[Any]:
    rect = _box_rect(box)
    if rect is None:
        return []
    x1, y1, x2, y2 = rect
    text_length = max(len(text), 1)
    advance = (x2 - x1) / text_length
    chars = []
    for index, char_text in enumerate(text):
        char_box = type("SyntheticBox", (), {})()
        char_box.x = x1 + advance * index
        char_box.x2 = x1 + advance * (index + 1)
        char_box.y = y1
        char_box.y2 = y2
        synthetic_char = type("SyntheticChar", (), {})()
        synthetic_char.char_unicode = char_text
        synthetic_char.box = char_box
        synthetic_char.pdf_style = style
        chars.append(synthetic_char)
    return chars


def _normalize_pdf_font_traits(font: Any, samples: list[dict[str, Any]]) -> int:
    font_name = str(getattr(font, "name", "") or getattr(font, "font_id", "") or "")
    if not font_name:
        return 0
    inferred = _infer_font_traits_from_name(font_name)
    if inferred is None:
        return 0
    changed = False
    before = {
        "bold": getattr(font, "bold", None),
        "italic": getattr(font, "italic", None),
        "monospace": getattr(font, "monospace", None),
        "serif": getattr(font, "serif", None),
    }
    for key, value in inferred.items():
        if value is None or getattr(font, key, None) == value:
            continue
        setattr(font, key, value)
        changed = True
    if not changed:
        return 0
    if len(samples) < 8:
        samples.append(
            {
                "font_id": getattr(font, "font_id", None),
                "name": font_name,
                "before": before,
                "after": {key: getattr(font, key, None) for key in before},
            }
        )
    return 1


def _infer_font_traits_from_name(font_name: str) -> dict[str, int | None] | None:
    normalized = re.sub(r"[^a-z0-9]+", "", font_name.lower())
    if not normalized:
        return None
    bold = 1 if any(token in normalized for token in ("bold", "black", "heavy", "semibold", "demibold", "demi")) else 0
    italic = 1 if any(token in normalized for token in ("italic", "oblique")) else 0
    monospace = 1 if any(token in normalized for token in ("mono", "courier", "consolas", "menlo", "monaco", "code")) else 0
    serif: int | None = None
    if any(hint in normalized for hint in _SANS_FONT_NAME_HINTS):
        serif = 0
    elif any(hint in normalized for hint in _SERIF_FONT_NAME_HINTS):
        serif = 1
    if serif is None and bold == 0 and italic == 0 and monospace == 0:
        return None
    return {
        "bold": bold,
        "italic": italic,
        "monospace": monospace,
        "serif": serif,
    }


def _should_normalize_translated_run_font_size(text: str, current_size: float, base_size: float) -> bool:
    if current_size <= 0 or base_size <= 0:
        return False
    if math.isclose(current_size, base_size, rel_tol=0.02, abs_tol=0.15):
        return False
    normalized = _strip_babeldoc_style_placeholders(text).strip()
    if not normalized or _is_size_sensitive_inline_marker(normalized):
        return False
    return _looks_like_translated_prose_segment(normalized)


def _is_size_sensitive_inline_marker(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    if re.fullmatch(r"[\W_]+", normalized):
        return True
    if re.fullmatch(r"[\(\[]?\d{1,3}[A-Za-z]?[\)\]]?", normalized):
        return True
    if _TECHNICAL_NUMBER_UNIT_RE.fullmatch(normalized):
        return True
    if _TECHNICAL_IDENTIFIER_RE.fullmatch(normalized):
        return True
    if _TECHNICAL_UNIT_RE.fullmatch(normalized):
        return True
    if _SHORT_UPPER_TOKEN_RE.fullmatch(normalized):
        return True
    return False


def _looks_like_translated_prose_segment(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    letter_count = sum(1 for char in normalized if char.isalpha())
    if letter_count >= 4:
        return True
    return " " in normalized and letter_count >= 2


def _looks_like_vertical_axis_text(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    short_lines = sum(1 for line in lines if len(line) <= 2 or _NUMERIC_OR_SYMBOL_RE.fullmatch(line))
    has_axis_words = any(any(char.isalpha() for char in line) and len(line) > 4 for line in lines)
    return has_axis_words and short_lines / len(lines) >= 0.35


def _looks_like_axis_label_fragment(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    alpha_chars = sum(1 for line in lines for char in line if char.isalpha())
    has_unit_fragment = any(re.fullmatch(r"[A-Za-zµμ%]+", line) for line in lines)
    short_lines = sum(1 for line in lines if len(line) <= 3 or _NUMERIC_OR_SYMBOL_RE.fullmatch(line))
    return alpha_chars >= 4 and short_lines / len(lines) >= 0.35 and (has_unit_fragment or len(lines) >= 4)


def _should_preserve_dynamic_text(text: str) -> bool:
    if _looks_like_axis_label_fragment(text):
        return True
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    short_lines = sum(1 for line in lines if len(line) <= 3 or _NUMERIC_OR_SYMBOL_RE.fullmatch(line))
    axis_fragment = any(any(char.isalpha() for char in line) and len(line) > 3 for line in lines)
    numeric_ticks = sum(1 for line in lines if re.fullmatch(r"[-+]?\s*\d+(?:\.\d+)?", line))
    unit_fragment = any(re.fullmatch(r"[A-Za-zµμ]+", line) for line in lines)
    return short_lines / len(lines) >= 0.5 and numeric_ticks >= 2 and (axis_fragment or unit_fragment)


def _is_diagnostic_sample(text: str) -> bool:
    return (
        _split_toc_entry(text) is not None
        or _has_inline_numbered_markers(text)
        or _looks_like_vertical_axis_text(text)
        or _looks_like_axis_label_fragment(text)
    )



def _eligible_repeated_text(record: _ParagraphRecord) -> bool:
    text = record.canonical_text
    if len(text) < 3 or len(text) > 160:
        return False
    return any(char.isalpha() for char in text)


def _is_edge_band(record: _ParagraphRecord) -> bool:
    if record.rect is None or record.page_rect is None:
        return False
    x1, y1, x2, y2 = record.rect
    px1, py1, px2, py2 = record.page_rect
    width = max(px2 - px1, 1.0)
    height = max(py2 - py1, 1.0)
    return (
        y1 <= py1 + height * 0.1
        or y2 >= py2 - height * 0.1
        or x1 <= px1 + width * 0.06
        or x2 >= px2 - width * 0.06
    )


def _is_copyable_unicode_composition(composition: list[Any]) -> bool:
    if not composition:
        return False
    for item in composition:
        if getattr(item, "pdf_same_style_unicode_characters", None) is None:
            return False
    return True


def _is_inline_punctuation_fragment(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    return bool(normalized) and len(normalized) <= 2 and _INLINE_PUNCTUATION_FRAGMENT_RE.fullmatch(normalized) is not None


def _supports_visual_line_split(paragraph: Any) -> bool:
    return getattr(paragraph, "layout_label", None) in {"fallback_line", "plain text", "table_footnote", "abandon"}


def _split_paragraph_by_visual_lines(paragraph: Any) -> list[Any]:
    composition = list(getattr(paragraph, "pdf_paragraph_composition", []) or [])
    if not composition:
        return [paragraph]
    line_items: list[tuple[Any, tuple[float, float, float, float]]] = []
    for item in composition:
        line_items.extend(_split_composition_item_by_visual_lines(item))
    if len(line_items) < 2:
        return [paragraph]
    ordered_items = sorted(
        line_items,
        key=lambda item: _visual_line_item_sort_key(item[1]),
    )
    grouped_lines: list[dict[str, Any]] = []
    for item, rect in ordered_items:
        if grouped_lines and _same_visual_line(grouped_lines[-1]["rect"], rect):
            grouped_lines[-1]["fragments"].append((item, rect))
            grouped_lines[-1]["rect"] = _rect_union([grouped_lines[-1]["rect"], rect])
            continue
        grouped_lines.append({"fragments": [(item, rect)], "rect": rect})
    if len(grouped_lines) < 2:
        return [paragraph]
    if not _should_split_visual_line_groups(paragraph, grouped_lines):
        return [paragraph]
    split_paragraphs = []
    split_index = 1
    for group in grouped_lines:
        fragment_groups = _refine_fallback_line_fragment_groups(paragraph, group["fragments"])
        for fragment_group in fragment_groups:
            split_paragraph = copy.deepcopy(paragraph)
            ordered_group_items = [item for item, _rect in sorted(fragment_group, key=lambda fragment: fragment[1][0])]
            split_paragraph.pdf_paragraph_composition = ordered_group_items
            split_paragraph.unicode = _composition_text(ordered_group_items)
            group_rect = _rect_union([_composition_item_rect(item) for item in ordered_group_items]) or group["rect"]
            _set_box_rect(getattr(split_paragraph, "box", None), group_rect)
            if hasattr(split_paragraph, "debug_id") and getattr(split_paragraph, "debug_id", None):
                split_paragraph.debug_id = f"{split_paragraph.debug_id}:vline:{split_index}"
            split_paragraph.optimal_scale = None
            split_paragraphs.append(split_paragraph)
            split_index += 1
    return split_paragraphs


def _should_split_visual_line_groups(paragraph: Any, grouped_lines: list[dict[str, Any]]) -> bool:
    layout_label = getattr(paragraph, "layout_label", None)
    if layout_label == "fallback_line":
        return True
    if layout_label not in {"plain text", "table_footnote", "abandon"}:
        return False
    paragraph_rect = _box_rect(getattr(paragraph, "box", None))
    if paragraph_rect is None:
        return False
    line_rects = [group.get("rect") for group in grouped_lines if group.get("rect") is not None]
    if len(line_rects) < 2:
        return False
    paragraph_width = max(paragraph_rect[2] - paragraph_rect[0], 1.0)
    paragraph_height = max(paragraph_rect[3] - paragraph_rect[1], 1.0)
    line_heights = [max(rect[3] - rect[1], 1.0) for rect in line_rects]
    line_centers = [((rect[1] + rect[3]) / 2) for rect in line_rects]
    sorted_centers = sorted(line_centers, reverse=True)
    baseline_gaps = [abs(current - following) for current, following in zip(sorted_centers, sorted_centers[1:])]
    meaningful_gaps = [
        gap for gap in baseline_gaps if gap >= max(6.0, min(line_heights) * 0.7)
    ]
    if len(meaningful_gaps) < 1:
        return False
    if paragraph_height < max(18.0, min(line_heights) * 1.8):
        return False
    if layout_label == "abandon":
        return len(line_rects) >= 3 or paragraph_height >= max(26.0, min(line_heights) * 2.4)
    wide_line_count = sum(1 for rect in line_rects if (rect[2] - rect[0]) / paragraph_width >= 0.58)
    if wide_line_count < 2:
        return False
    return True


def _refine_fallback_line_fragment_groups(
    paragraph: Any,
    fragments: list[tuple[Any, tuple[float, float, float, float]]],
) -> list[list[tuple[Any, tuple[float, float, float, float]]]]:
    if getattr(paragraph, "layout_label", None) != "fallback_line":
        return [fragments]
    expanded: list[tuple[Any, tuple[float, float, float, float]]] = []
    for item, _rect in fragments:
        expanded.extend(_split_multiline_fallback_line_item(item))
    if len(expanded) < 2:
        return [expanded] if expanded else [fragments]
    text = _composition_text([item for item, _rect in expanded]).strip()
    if not _looks_like_splitworthy_multiline_fallback_text(text):
        return [expanded]
    groups: list[list[tuple[Any, tuple[float, float, float, float]]]] = [[expanded[0]]]
    previous_rect = expanded[0][1]
    previous_item = expanded[0][0]
    for item, rect in expanded[1:]:
        if _should_split_fallback_line_fragment_cluster(previous_item, previous_rect, item, rect):
            groups.append([(item, rect)])
        else:
            groups[-1].append((item, rect))
        previous_item = item
        previous_rect = rect
    return groups


def _split_multiline_fallback_line_item(item: Any) -> list[tuple[Any, tuple[float, float, float, float]]]:
    same_style = getattr(item, "pdf_same_style_characters", None)
    if same_style is None:
        rect = _composition_item_rect(item)
        return [(item, rect)] if rect is not None else []
    chars = list(getattr(same_style, "pdf_character", []) or [])
    if len(chars) < 2:
        rect = _composition_item_rect(item)
        return [(item, rect)] if rect is not None else []
    text = _characters_text(chars).strip()
    if not _looks_like_splitworthy_multiline_fallback_text(text):
        rect = _composition_item_rect(item)
        return [(item, rect)] if rect is not None else []
    char_groups = _split_chars_by_horizontal_gap(chars)
    if len(char_groups) <= 1:
        rect = _composition_item_rect(item)
        return [(item, rect)] if rect is not None else []
    fragments: list[tuple[Any, tuple[float, float, float, float]]] = []
    for group in char_groups:
        rect = _rect_union([_box_rect(getattr(char, "box", None)) for char in group])
        if rect is None:
            continue
        fragment = copy.deepcopy(item)
        fragment_same_style = getattr(fragment, "pdf_same_style_characters", None)
        fragment_same_style.pdf_character = group
        _set_box_rect(getattr(fragment_same_style, "box", None), rect)
        fragments.append((fragment, rect))
    if fragments:
        return fragments
    rect = _composition_item_rect(item)
    return [(item, rect)] if rect is not None else []


def _looks_like_splitworthy_multiline_fallback_text(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not normalized or " " not in normalized:
        return False
    if any("\u4e00" <= char <= "\u9fff" for char in normalized):
        return False
    if re.search(r"[a-z]", normalized):
        return False
    if re.fullmatch(r"[A-Z0-9/._:+%#@&=\-() ]+", normalized) is None:
        return False
    return sum(1 for token in normalized.split() if token) >= 2


def _split_chars_by_horizontal_gap(chars: list[Any]) -> list[list[Any]]:
    ordered: list[tuple[tuple[float, float, float, float], Any]] = []
    for char in chars:
        rect = _box_rect(getattr(char, "box", None))
        if rect is None:
            continue
        ordered.append((rect, char))
    if len(ordered) <= 1:
        return [[char for _rect, char in ordered]] if ordered else []
    ordered.sort(key=lambda item: (item[0][0], item[0][1], item[0][2]))
    groups: list[list[Any]] = [[ordered[0][1]]]
    previous_rect = ordered[0][0]
    previous_char = ordered[0][1]
    for rect, char in ordered[1:]:
        gap = rect[0] - previous_rect[2]
        previous_style = getattr(groups[-1][-1], "pdf_style", None)
        current_style = getattr(char, "pdf_style", None)
        previous_font_size = float(getattr(previous_style, "font_size", 0) or 0)
        current_font_size = float(getattr(current_style, "font_size", 0) or 0)
        font_sizes = [size for size in (previous_font_size, current_font_size) if size > 0]
        gap_limit = max(4.0, (min(font_sizes) * 0.52) if font_sizes else 4.0)
        if gap > gap_limit or _fallback_line_token_break(previous_char, char):
            groups.append([char])
        else:
            groups[-1].append(char)
        previous_rect = rect
        previous_char = char
    return groups


def _fallback_line_token_break(previous_char: Any, current_char: Any) -> bool:
    current_text = str(getattr(current_char, "char_unicode", "") or "")
    if not current_text:
        return False
    return _needs_implicit_space(None, previous_char, current_char, current_text)


def _should_split_fallback_line_fragment_cluster(
    previous_item: Any,
    previous_rect: tuple[float, float, float, float],
    current_item: Any,
    current_rect: tuple[float, float, float, float],
) -> bool:
    gap = current_rect[0] - previous_rect[2]
    previous_text = _composition_text([previous_item]).strip()
    current_text = _composition_text([current_item]).strip()
    previous_height = max(previous_rect[3] - previous_rect[1], 1.0)
    current_height = max(current_rect[3] - current_rect[1], 1.0)
    gap_limit = max(6.0, min(previous_height, current_height) * 0.7)
    if gap <= gap_limit:
        return False
    if previous_text == "_" or current_text == "_":
        return False
    return True


def _fallback_line_split_tokens_with_underscore_context(paragraph: Any, paragraphs: list[Any], index: int) -> list[Any]:
    if getattr(paragraph, "layout_label", None) != "fallback_line":
        return [paragraph]
    text = unicodedata.normalize("NFKC", str(getattr(paragraph, "unicode", "") or "")).strip()
    if not _looks_like_splitworthy_multiline_fallback_text(text):
        return [paragraph]
    paragraph_rect = _box_rect(getattr(paragraph, "box", None))
    if paragraph_rect is None:
        return [paragraph]
    parts = _split_fallback_line_paragraph_items(paragraph)
    if len(parts) <= 1:
        return [paragraph]
    split_parts = [item for item, _rect in parts]
    if not _has_underscore_neighbors(paragraphs, paragraph_rect):
        return [paragraph]
    return split_parts


def _split_fallback_line_paragraph_items(paragraph: Any) -> list[tuple[Any, tuple[float, float, float, float]]]:
    expanded: list[tuple[Any, tuple[float, float, float, float]]] = []
    for item in getattr(paragraph, "pdf_paragraph_composition", []) or []:
        expanded.extend(_split_multiline_fallback_line_item(item))
    return expanded


def _has_underscore_neighbors(paragraphs: list[Any], paragraph_rect: tuple[float, float, float, float]) -> bool:
    paragraph_height = max(paragraph_rect[3] - paragraph_rect[1], 1.0)
    for neighbor in paragraphs:
        if getattr(neighbor, "layout_label", None) != "fallback_line":
            continue
        neighbor_text = unicodedata.normalize("NFKC", str(getattr(neighbor, "unicode", "") or "")).strip()
        if neighbor_text != "_":
            continue
        neighbor_rect = _box_rect(getattr(neighbor, "box", None))
        if neighbor_rect is None:
            continue
        horizontal_gap = min(abs(neighbor_rect[0] - paragraph_rect[2]), abs(paragraph_rect[0] - neighbor_rect[2]))
        if horizontal_gap > paragraph_height * 8.0:
            continue
        if _same_baseline_close_gap(paragraph_rect, neighbor_rect)[0] or _same_baseline_close_gap(neighbor_rect, paragraph_rect)[0]:
            return True
        overlap = min(paragraph_rect[3], neighbor_rect[3]) - max(paragraph_rect[1], neighbor_rect[1])
        if overlap > 0:
            return True
    return False


def _can_merge_fallback_line_underscore_compound(left: Any, middle: Any, right: Any) -> bool:
    if any(getattr(paragraph, "layout_label", None) != "fallback_line" for paragraph in (left, middle, right)):
        return False
    left_text = unicodedata.normalize("NFKC", str(getattr(left, "unicode", "") or "")).strip()
    middle_text = unicodedata.normalize("NFKC", str(getattr(middle, "unicode", "") or "")).strip()
    right_text = unicodedata.normalize("NFKC", str(getattr(right, "unicode", "") or "")).strip()
    if middle_text != "_" or not left_text or not right_text:
        return False
    if re.fullmatch(r"[A-Z0-9]+", left_text) is None:
        return False
    if re.fullmatch(r"[A-Z0-9]+", right_text) is None:
        return False
    left_rect = _box_rect(getattr(left, "box", None))
    middle_rect = _box_rect(getattr(middle, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or middle_rect is None or right_rect is None:
        return False
    if getattr(left, "xobj_id", None) != getattr(middle, "xobj_id", None) or getattr(left, "xobj_id", None) != getattr(right, "xobj_id", None):
        return False
    if not _same_fallback_line_band(left_rect, middle_rect, right_rect):
        return False
    if not _is_tight_underscore_bridge(left_rect, middle_rect) or not _is_tight_underscore_bridge(middle_rect, right_rect):
        return False
    return True


def _same_fallback_line_band(
    left_rect: tuple[float, float, float, float],
    middle_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    centers = [((rect[1] + rect[3]) / 2) for rect in (left_rect, middle_rect, right_rect)]
    heights = [max(rect[3] - rect[1], 1.0) for rect in (left_rect, middle_rect, right_rect)]
    return max(centers) - min(centers) <= max(heights) * 0.55


def _is_tight_underscore_bridge(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    gap = right_rect[0] - left_rect[2]
    height = max(min(left_rect[3] - left_rect[1], right_rect[3] - right_rect[1]), 1.0)
    return -2.0 <= gap <= max(6.0, height * 0.8)


def _split_composition_item_by_visual_lines(item: Any) -> list[tuple[Any, tuple[float, float, float, float]]]:
    same_style = getattr(item, "pdf_same_style_characters", None)
    if same_style is not None:
        chars = list(getattr(same_style, "pdf_character", []) or [])
        char_groups = _group_characters_by_visual_line(chars)
        if len(char_groups) <= 1:
            rect = _composition_item_rect(item)
            return [(copy.deepcopy(item), rect)] if rect is not None else []
        fragments = []
        for group in char_groups:
            rect = _rect_union([_box_rect(getattr(char, "box", None)) for char in group])
            if rect is None:
                continue
            fragment = copy.deepcopy(item)
            fragment_same_style = getattr(fragment, "pdf_same_style_characters", None)
            fragment_same_style.pdf_character = group
            _set_box_rect(getattr(fragment_same_style, "box", None), rect)
            fragments.append((fragment, rect))
        return fragments
    rect = _composition_item_rect(item)
    return [(copy.deepcopy(item), rect)] if rect is not None else []


def _group_characters_by_visual_line(chars: list[Any]) -> list[list[Any]]:
    ordered = []
    for char in chars:
        rect = _box_rect(getattr(char, "box", None))
        if rect is None:
            continue
        ordered.append((rect, char))
    if len(ordered) <= 1:
        return [[char for _rect, char in ordered]] if ordered else []
    ordered.sort(key=lambda item: _visual_line_item_sort_key(item[0]))
    groups: list[dict[str, Any]] = []
    for rect, char in ordered:
        if groups and _same_visual_line(groups[-1]["rect"], rect):
            groups[-1]["chars"].append(char)
            groups[-1]["rect"] = _rect_union([groups[-1]["rect"], rect])
            continue
        groups.append({"chars": [char], "rect": rect})
    return [group["chars"] for group in groups]


def _visual_line_item_sort_key(rect: tuple[float, float, float, float]) -> tuple[float, float, float]:
    x1, y1, _x2, y2 = rect
    return (-y2, x1, -y1)


def _same_visual_line(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    left_height = max(left_rect[3] - left_rect[1], 1.0)
    right_height = max(right_rect[3] - right_rect[1], 1.0)
    overlap = min(left_rect[3], right_rect[3]) - max(left_rect[1], right_rect[1])
    if overlap / min(left_height, right_height) >= 0.45:
        return True
    center_delta = abs(((left_rect[1] + left_rect[3]) / 2) - ((right_rect[1] + right_rect[3]) / 2))
    return center_delta <= max(left_height, right_height) * 0.55


def _composition_item_rect(item: Any) -> tuple[float, float, float, float] | None:
    same_style = getattr(item, "pdf_same_style_characters", None)
    if same_style is not None:
        char_rects = [_box_rect(getattr(char, "box", None)) for char in getattr(same_style, "pdf_character", []) or []]
        rect = _rect_union(char_rects)
        if rect is not None:
            return rect
        return _box_rect(getattr(same_style, "box", None))
    same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
    if same_style_unicode is not None:
        return _box_rect(getattr(same_style_unicode, "box", None))
    formula = getattr(item, "pdf_formula", None)
    if formula is not None:
        return _box_rect(getattr(formula, "box", None))
    char = getattr(item, "pdf_character", None)
    if char is not None:
        return _box_rect(getattr(char, "box", None))
    line = getattr(item, "pdf_line", None)
    if line is not None:
        return _box_rect(getattr(line, "box", None))
    return None


def _composition_text(composition: list[Any]) -> str:
    parts: list[str] = []
    for item in composition:
        same_style = getattr(item, "pdf_same_style_characters", None)
        if same_style is not None:
            parts.append(_characters_text(list(getattr(same_style, "pdf_character", []) or [])))
            continue
        same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
        if same_style_unicode is not None:
            parts.append(str(getattr(same_style_unicode, "unicode", "") or ""))
            continue
        formula = getattr(item, "pdf_formula", None)
        if formula is not None:
            parts.append(_characters_text(list(getattr(formula, "pdf_character", []) or [])))
            continue
        char = getattr(item, "pdf_character", None)
        if char is not None:
            parts.append(str(getattr(char, "char_unicode", "") or ""))
            continue
        line = getattr(item, "pdf_line", None)
        if line is not None:
            parts.append(str(getattr(line, "unicode", "") or ""))
    return "".join(parts)


def _rebuild_fallback_line_text(paragraph: Any) -> str | None:
    chars = _collect_fallback_line_chars(paragraph)
    if len(chars) < 2:
        return None
    if not _looks_like_single_line_fallback_label(paragraph, chars):
        return None
    rebuilt = _rebuild_compact_technical_label_text(paragraph, chars)
    if rebuilt is None:
        ordered = sorted(chars, key=_fallback_line_char_sort_key)
        rebuilt = _fallback_line_text_from_chars(ordered).strip()
    return rebuilt or None


def _collect_fallback_line_chars(paragraph: Any) -> list[Any]:
    chars: list[Any] = []
    for item in getattr(paragraph, "pdf_paragraph_composition", []) or []:
        same_style = getattr(item, "pdf_same_style_characters", None)
        if same_style is not None:
            chars.extend(char for char in getattr(same_style, "pdf_character", []) or [] if _box_rect(getattr(char, "box", None)) is not None)
            continue
        formula = getattr(item, "pdf_formula", None)
        if formula is not None:
            chars.extend(char for char in getattr(formula, "pdf_character", []) or [] if _box_rect(getattr(char, "box", None)) is not None)
            continue
        char = getattr(item, "pdf_character", None)
        if char is not None and _box_rect(getattr(char, "box", None)) is not None:
            chars.append(char)
    return chars


def _rebuild_compact_technical_label_text(paragraph: Any, chars: list[Any]) -> str | None:
    if not _is_compact_technical_label_candidate(paragraph, chars):
        return None
    ordered = _sort_compact_technical_label_chars(chars)
    if len(ordered) < 2:
        return None
    rebuilt = _fallback_line_text_from_chars(ordered).strip()
    if not rebuilt:
        return None
    return _normalize_compact_technical_label_text(rebuilt)


def _is_compact_technical_label_candidate(paragraph: Any, chars: list[Any]) -> bool:
    layout_label = getattr(paragraph, "layout_label", None)
    if layout_label not in {"fallback_line", "figure_caption"}:
        return False
    source_text = unicodedata.normalize("NFKC", str(getattr(paragraph, "unicode", "") or "")).strip()
    compact = _SPACE_COLLAPSE_RE.sub("", source_text)
    if not compact or len(compact) > 48:
        return False
    if len(chars) < 4:
        return False
    if "\n" in source_text:
        return False
    technical_signals = (
        _TECHNICAL_IDENTIFIER_RE.search(source_text),
        _TECHNICAL_NUMBER_UNIT_RE.search(source_text),
        _TECHNICAL_RATIO_TOKEN_RE.search(source_text),
        _TECHNICAL_UNIT_RE.search(source_text),
        re.search(r"[=()/±°^]|[A-Z]\d", source_text),
    )
    if not any(technical_signals):
        return False
    return True


def _sort_compact_technical_label_chars(chars: list[Any]) -> list[Any]:
    annotated: list[tuple[Any, tuple[float, float, float, float], float, float, float]] = []
    base_center_y = _dominant_compact_label_baseline(chars)
    for char in chars:
        rect = _box_rect(getattr(char, "box", None))
        if rect is None:
            continue
        x1, y1, x2, y2 = rect
        center_y = (y1 + y2) / 2
        rank = 0.0
        if base_center_y is not None:
            if center_y <= base_center_y - 0.8:
                rank = 1.0
            elif center_y >= base_center_y + 0.8:
                rank = -1.0
        annotated.append((char, rect, x1, rank, center_y))
    annotated.sort(key=lambda item: (item[2], item[3], item[4]))
    return [item[0] for item in annotated]


def _dominant_compact_label_baseline(chars: list[Any]) -> float | None:
    buckets: dict[int, list[float]] = {}
    for char in chars:
        rect = _box_rect(getattr(char, "box", None))
        if rect is None:
            continue
        center_y = (rect[1] + rect[3]) / 2
        bucket = round(center_y * 2)
        buckets.setdefault(bucket, []).append(center_y)
    if not buckets:
        return None
    _bucket, values = max(buckets.items(), key=lambda item: (len(item[1]), item[0]))
    return sum(values) / len(values)


def _normalize_compact_technical_label_text(text: str) -> str:
    normalized = _normalize_fallback_line_token_spacing(text)
    normalized = re.sub(r"(?<![A-Za-z])I\s*C(?![A-Za-z])", "I2C", normalized)
    normalized = re.sub(r"\(\s+\)", "()", normalized)
    return normalized


def _looks_like_single_line_fallback_label(paragraph: Any, chars: list[Any]) -> bool:
    rect = _box_rect(getattr(paragraph, "box", None))
    if rect is None:
        return False
    height = rect[3] - rect[1]
    font_sizes = []
    for char in chars:
        style = getattr(char, "pdf_style", None)
        font_size = float(getattr(style, "font_size", 0) or 0)
        if font_size > 0:
            font_sizes.append(font_size)
    if not font_sizes:
        return False
    reference_size = max(font_sizes)
    return height <= min(reference_size * 1.85 + 1.0, 12.5)


def _fallback_line_char_sort_key(char: Any) -> tuple[float, float, float]:
    rect = _box_rect(getattr(char, "box", None))
    if rect is None:
        return (math.inf, math.inf, math.inf)
    x1, y1, _x2, y2 = rect
    return (x1, (y1 + y2) / 2, y1)


def _fallback_line_text_from_chars(chars: list[Any]) -> str:
    parts: list[str] = []
    previous = None
    for char in chars:
        current_text = str(getattr(char, "char_unicode", "") or "")
        if not current_text:
            previous = char
            continue
        if previous is not None and _should_insert_fallback_line_space(previous, char, current_text):
            parts.append(" ")
        parts.append(current_text)
        previous = char
    return _normalize_fallback_line_token_spacing("".join(parts))


def _should_insert_fallback_line_space(previous: Any, current: Any, current_text: str) -> bool:
    previous_text = str(getattr(previous, "char_unicode", "") or "")
    if not previous_text or previous_text.isspace() or current_text.isspace():
        return False
    if _is_numeric_internal_punctuation_boundary("", previous_text, current_text):
        return False
    if previous_text[-1] in "/_-(" or current_text[0] in "/_-)":
        return False
    previous_rect = _box_rect(getattr(previous, "box", None))
    current_rect = _box_rect(getattr(current, "box", None))
    if previous_rect is None or current_rect is None:
        return False
    gap = current_rect[0] - previous_rect[2]
    if gap <= 0:
        return False
    previous_style = getattr(previous, "pdf_style", None)
    current_style = getattr(current, "pdf_style", None)
    previous_font_size = float(getattr(previous_style, "font_size", 0) or 0)
    current_font_size = float(getattr(current_style, "font_size", 0) or 0)
    font_sizes = [size for size in (previous_font_size, current_font_size) if size > 0]
    font_size = min(font_sizes) if font_sizes else 0.0
    left_char = previous_text[-1]
    right_char = current_text[0]
    threshold = max(1.8, font_size * 0.22 if font_size > 0 else 1.8)
    if left_char.islower() and right_char.isupper():
        threshold = max(1.1, font_size * 0.16 if font_size > 0 else 1.1)
    if gap < threshold:
        return False
    if current_text in {".", ",", ";", ":", "!", "?", "%", ")", "]", "}"}:
        return False
    return True


def _normalize_fallback_line_token_spacing(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    normalized = re.sub(r"\(\s+", "(", normalized)
    normalized = re.sub(r"\s+\)", ")", normalized)
    tokens = normalized.split()
    if len(tokens) < 2:
        return normalized
    merged: list[str] = [tokens[0]]
    for token in tokens[1:]:
        if _should_merge_fallback_line_tokens(merged[-1], token):
            merged[-1] = f"{merged[-1]}{token}"
            continue
        merged.append(token)
    return " ".join(merged)


def _should_merge_fallback_line_tokens(left: str, right: str) -> bool:
    if not left or not right:
        return False
    left_last = left[-1]
    right_first = right[0]
    if left_last in "(/_-" or right_first in "/_-)":
        return True
    if _looks_like_compact_technical_token_join(left, right):
        return True
    if len(left) == 1 or len(right) == 1:
        return any(char.isalnum() for char in (left_last, right_first))
    if left_last.isupper() and right_first.isupper() and min(len(left), len(right)) <= 2:
        return True
    return False


def _looks_like_compact_technical_token_join(left: str, right: str) -> bool:
    combined = f"{left}{right}"
    if not any(char.isalnum() for char in combined):
        return False
    if re.fullmatch(r"[A-Za-z]+", left) and re.fullmatch(r"[A-Za-z]+", right):
        return False
    if re.fullmatch(r"[A-Za-z0-9-]+", left) and re.fullmatch(r"[A-Za-z]+", right):
        if not re.search(r"[/_]|(?:[A-Z]{2,}\d|\d[A-Z]{2,}|\d/)", right):
            return False
    patterns = (
        _TECHNICAL_NUMBER_UNIT_RE,
        _TECHNICAL_RATIO_TOKEN_RE,
        _TECHNICAL_UNIT_RE,
        _TECHNICAL_IDENTIFIER_RE,
        _TECHNICAL_COMPOUND_IDENTIFIER_RE,
        _TECHNICAL_COMPACT_EQUATION_RE,
        _DIMENSION_CHAIN_RE,
        _PLACEHOLDER_BRIDGED_DIMENSION_CHAIN_RE,
    )
    if any(pattern.fullmatch(combined) for pattern in patterns):
        return True
    if re.fullmatch(r"[A-Z]{2,}\d+(?:[/.-]\d+)*(?:/[A-Z0-9]+)*", combined):
        return True
    if re.fullmatch(r"[A-Za-z]+(?:/[A-Z]{2,}[A-Z0-9]*)+", combined):
        return True
    if re.fullmatch(r"[A-Z]\d[A-Z](?:[-/][A-Za-z][A-Za-z0-9-]*)?", combined):
        return True
    return False


def _is_small_fallback_line_fragment(paragraph: Any) -> bool:
    if getattr(paragraph, "layout_label", None) != "fallback_line":
        return False
    chars = _collect_fallback_line_chars(paragraph)
    if not _looks_like_single_line_fallback_label(paragraph, chars):
        return False
    text = unicodedata.normalize("NFKC", str(getattr(paragraph, "unicode", "") or "")).strip()
    collapsed = _SPACE_COLLAPSE_RE.sub("", text)
    if not collapsed or len(collapsed) != 1:
        return False
    return collapsed.isdigit()


def _fallback_line_fragment_attachment_score(fragment: Any, target: Any) -> float | None:
    if _is_fallback_line_underscore_band_paragraph(fragment) or _is_fallback_line_underscore_band_paragraph(target):
        return None
    if getattr(target, "layout_label", None) != "fallback_line":
        return None
    fragment_text = unicodedata.normalize("NFKC", str(getattr(fragment, "unicode", "") or "")).strip()
    target_text = unicodedata.normalize("NFKC", str(getattr(target, "unicode", "") or "")).strip()
    if not fragment_text or not target_text or _is_small_fallback_line_fragment(target):
        return None
    if _creates_ambiguous_numeric_token(fragment_text, target_text):
        return None
    if getattr(fragment, "xobj_id", None) != getattr(target, "xobj_id", None):
        return None
    fragment_rect = _box_rect(getattr(fragment, "box", None))
    target_rect = _box_rect(getattr(target, "box", None))
    if fragment_rect is None or target_rect is None:
        return None
    if not _looks_like_superscript_or_subscript_fragment(fragment_rect, target_rect):
        return None
    fragment_width = fragment_rect[2] - fragment_rect[0]
    target_width = target_rect[2] - target_rect[0]
    target_height = max(target_rect[3] - target_rect[1], 1.0)
    if target_height > 10.5:
        return None
    if target_width <= 0 or fragment_width > target_width * 0.4:
        return None
    fragment_height = max(fragment_rect[3] - fragment_rect[1], 1.0)
    if fragment_rect[1] <= target_rect[3] and fragment_rect[3] >= target_rect[1]:
        return None
    fragment_center_x = _rect_center_x(fragment_rect)
    if fragment_center_x > target_rect[0] + target_width * 0.45:
        return None
    horizontal_cover = target_rect[0] - 3.0 <= fragment_center_x <= target_rect[2] + 3.0
    left_gap = abs(fragment_rect[2] - target_rect[0])
    right_gap = abs(fragment_rect[0] - target_rect[2])
    if not horizontal_cover and min(left_gap, right_gap) > max(fragment_height, target_height) * 1.8:
        return None
    vertical_gap = min(abs(fragment_rect[1] - target_rect[3]), abs(target_rect[1] - fragment_rect[3]))
    if vertical_gap > max(fragment_height, target_height) * 1.2:
        return None
    union_rect = _rect_union([fragment_rect, target_rect])
    if union_rect is None:
        return None
    union_height = union_rect[3] - union_rect[1]
    if union_height > max(fragment_height, target_height) * 3.0:
        return None
    return vertical_gap + min(left_gap, right_gap)


def _creates_ambiguous_numeric_token(fragment_text: str, target_text: str) -> bool:
    fragment = unicodedata.normalize("NFKC", str(fragment_text or "")).strip()
    target = unicodedata.normalize("NFKC", str(target_text or "")).strip()
    if not fragment or not target:
        return False
    merged_left = f"{fragment}{target}"
    merged_right = f"{target}{fragment}"
    ambiguous_patterns = (
        r"[-+±]?\d+(?:[.,]\d+)?[A-Za-z]{2,}",
        r"[A-Za-z]{2,}[-+±]?\d+(?:[.,]\d+)?[A-Za-z]+",
    )
    return any(
        re.fullmatch(pattern, candidate) is not None
        for candidate in (merged_left, merged_right)
        for pattern in ambiguous_patterns
    )


def _detect_fallback_line_underscore_bands(records: list[_ParagraphRecord]) -> set[str]:
    grouped: dict[tuple[int, int | None], list[_ParagraphRecord]] = {}
    for record in records:
        if record.layout_label != "fallback_line" or record.rect is None:
            continue
        grouped.setdefault((record.page_number, record.xobj_id), []).append(record)
    protected: set[str] = set()
    for band_records in grouped.values():
        band_records.sort(key=lambda record: (record.rect[1], record.rect[0]))
        for record in band_records:
            if not _is_fallback_line_underscore_band_paragraph(record):
                continue
            protected.add(record.paragraph_id)
            base_rect = record.rect
            for candidate in band_records:
                if candidate.paragraph_id == record.paragraph_id or candidate.rect is None:
                    continue
                if _rects_share_fallback_line_band(base_rect, candidate.rect):
                    protected.add(candidate.paragraph_id)
    return protected


def _is_fallback_line_underscore_band_paragraph(paragraph_or_record: Any) -> bool:
    layout_label = getattr(paragraph_or_record, "layout_label", None)
    if layout_label != "fallback_line":
        return False
    text = unicodedata.normalize("NFKC", str(getattr(paragraph_or_record, "unicode", None) or getattr(paragraph_or_record, "text", "") or "")).strip()
    if not text:
        return False
    if text == "_":
        return True
    if _TECHNICAL_COMPOUND_IDENTIFIER_RE.fullmatch(text):
        return True
    if re.fullmatch(r"[A-Z0-9]{2,}", text):
        return True
    if re.fullmatch(r"[A-Z0-9]+\s+[A-Z0-9]+", text):
        return True
    return False


def _rects_share_fallback_line_band(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    left_height = max(left_rect[3] - left_rect[1], 1.0)
    right_height = max(right_rect[3] - right_rect[1], 1.0)
    center_delta = abs(((left_rect[1] + left_rect[3]) / 2) - ((right_rect[1] + right_rect[3]) / 2))
    if center_delta > max(left_height, right_height) * 1.2:
        return False
    horizontal_gap = min(abs(right_rect[0] - left_rect[2]), abs(left_rect[0] - right_rect[2]))
    return horizontal_gap <= max(left_height, right_height) * 8.0


def _looks_like_superscript_or_subscript_fragment(
    fragment_rect: tuple[float, float, float, float],
    target_rect: tuple[float, float, float, float],
) -> bool:
    target_height = max(target_rect[3] - target_rect[1], 1.0)
    fragment_height = max(fragment_rect[3] - fragment_rect[1], 1.0)
    if fragment_height > target_height * 0.92:
        return False
    target_center_y = (target_rect[1] + target_rect[3]) / 2
    fragment_center_y = (fragment_rect[1] + fragment_rect[3]) / 2
    return abs(fragment_center_y - target_center_y) >= target_height * 0.3


def _characters_text(chars: list[Any]) -> str:
    if not chars:
        return ""
    parts: list[str] = []
    previous = None
    previous_previous = None
    for char in chars:
        current_text = str(getattr(char, "char_unicode", "") or "")
        if not current_text:
            previous = char
            continue
        if previous is not None and _needs_implicit_space(previous_previous, previous, char, current_text):
            parts.append(" ")
        parts.append(current_text)
        previous_previous = previous
        previous = char
    return "".join(parts)


def _needs_implicit_space(previous_previous: Any, previous: Any, current: Any, current_text: str) -> bool:
    previous_text = str(getattr(previous, "char_unicode", "") or "")
    if not previous_text or previous_text.isspace() or current_text.isspace():
        return False
    previous_previous_text = str(getattr(previous_previous, "char_unicode", "") or "")
    if _is_numeric_internal_punctuation_boundary(previous_previous_text, previous_text, current_text):
        return False
    previous_rect = _box_rect(getattr(previous, "box", None))
    current_rect = _box_rect(getattr(current, "box", None))
    if previous_rect is None or current_rect is None:
        return False
    gap = current_rect[0] - previous_rect[2]
    if gap <= 0:
        return False
    previous_style = getattr(previous, "pdf_style", None)
    current_style = getattr(current, "pdf_style", None)
    previous_font_size = float(getattr(previous_style, "font_size", 0) or 0)
    current_font_size = float(getattr(current_style, "font_size", 0) or 0)
    font_sizes = [size for size in (previous_font_size, current_font_size) if size > 0]
    font_size = min(font_sizes) if font_sizes else 0.0
    threshold = max(1.8, font_size * 0.22 if font_size > 0 else 1.8)
    if gap < threshold:
        return False
    if current_text in {".", ",", ";", ":", "!", "?", "%", ")", "]", "}"}:
        return False
    return True


def _is_numeric_internal_punctuation_boundary(left_text: str, middle_text: str, right_text: str) -> bool:
    if middle_text not in {".", ","}:
        return False
    return bool(left_text) and bool(right_text) and left_text[-1].isdigit() and right_text[0].isdigit()
