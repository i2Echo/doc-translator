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

from doc_translator.hook_policy import HookPolicy


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
    r"\b(?:VDD|VSS|VCC|VREF|VIN|VOUT|VIH|VIL|VOH|VOL|GND|IOL|IOH|ISINK|IL|IH|TA|TJ|TS|TSTG|FCM|DR|PGA|ADC|I2C|UART|SCL|SDA|ADDR|ALERT|RDY|GPIO|TTL|DIV|FS|LSB|PPM)\b",
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
_VERTICAL_AXIS_LABEL_CROSS_PADDING = 0.35
_LAYOUT_MIN_COLUMN_CANDIDATES = 3
_LAYOUT_MIN_TWO_COLUMN_CANDIDATES = 6
_LAYOUT_TWO_COLUMN_MIN_GAP_POINTS = 36.0
_LAYOUT_TWO_COLUMN_MIN_GAP_PAGE_RATIO = 0.16
_LAYOUT_MIN_RECORDS_PER_COLUMN = 3
_LAYOUT_COLUMN_TOLERANCE_POINTS = 6.0
_LAYOUT_COLUMN_TOLERANCE_RATIO = 0.08
_LAYOUT_EDGE_CONFIDENCE = 0.9
_LAYOUT_VERTICAL_LABEL_CONFIDENCE = 0.82
_LAYOUT_TABLE_CONFIDENCE = 0.72
_LAYOUT_FIGURE_CONFIDENCE = 0.66
_LAYOUT_TWO_COLUMN_BODY_CONFIDENCE = 0.74
_LAYOUT_SINGLE_COLUMN_BODY_CONFIDENCE = 0.64
_BODY_SCALE_NORMALIZATION_MIN_GROUP_SIZE = 3
_BODY_SCALE_NORMALIZATION_MIN_SCALE = 0.62
_BODY_SCALE_NORMALIZATION_MIN_DELTA = 0.08
_BODY_SCALE_NORMALIZATION_MAX_TARGET = 0.88
_BODY_SCALE_NORMALIZATION_MIN_TEXT_WIDTH = 14
_BODY_SCALE_NORMALIZATION_ANCHOR_TEXT_WIDTH = 32
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


@dataclass(frozen=True, slots=True)
class _LayoutRegion:
    paragraph_id: str
    page_number: int
    region: str
    column_id: str | None
    confidence: float
    reason: str


@dataclass(frozen=True, slots=True)
class _PageLayoutSummary:
    page_number: int
    columns: tuple[tuple[str, float, float], ...]
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _OverlapCollapseCluster:
    ordered_group: tuple[tuple[int, Any], ...]
    base_index: int
    base: Any
    absorbed_indices: tuple[int, ...]
    merged_text: str
    merged_rect: tuple[float, float, float, float]


def _structure_plan_role_counts(plan: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in plan:
        roles = []
        for key in ("role", "left_role", "right_role"):
            role = item.get(key)
            if role:
                roles.append(str(role))
        multiplier = 1
        if item.get("kind") == "reconcile" and isinstance(item.get("follower_ids"), list):
            multiplier = max(len(item["follower_ids"]), 1)
        for role in roles or ["unknown"]:
            counts[role] = counts.get(role, 0) + multiplier
    return counts


@dataclass(slots=True)
class BabeldocHookContext:
    working_dir: Path | None = None
    target_language: str | None = None
    records_by_id: dict[str, _ParagraphRecord] = field(default_factory=dict)
    records_by_object_id: dict[int, _ParagraphRecord] = field(default_factory=dict)
    paragraphs_by_id: dict[str, Any] = field(default_factory=dict)
    groups: dict[str, list[str]] = field(default_factory=dict)
    layout_regions_by_id: dict[str, _LayoutRegion] = field(default_factory=dict)
    page_layout_summaries: dict[int, _PageLayoutSummary] = field(default_factory=dict)
    phase_events: list[dict[str, Any]] = field(default_factory=list)
    applied_events: list[dict[str, Any]] = field(default_factory=list)
    hook_policy: HookPolicy = field(default_factory=HookPolicy.from_env)
    axis_diagnostics: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"paragraph_candidates": [], "character_groups": []}
    )
    _translations: dict[str, _TranslationSnapshot] = field(default_factory=dict)
    _source_layouts: dict[str, _TranslationSnapshot] = field(default_factory=dict)
    _protected_tokens: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    _toc_prefix_width_by_id: dict[str, int] = field(default_factory=dict)
    _axis_label_translation_cache: dict[str, str] = field(default_factory=dict)
    _before_structure_snapshot: dict[str, Any] | None = None
    _after_structure_snapshot: dict[str, Any] | None = None
    _fallback_line_protected_bands: set[str] = field(default_factory=set)
    _postprocess_focus_paragraph_ids: set[int] = field(default_factory=set)
    _definition_style_restored_paragraph_ids: set[int] = field(default_factory=set)
    _symbol_font_ids_by_paragraph_object_id: dict[int, frozenset[str]] = field(default_factory=dict)
    _detached_i2c_visual_record_ids: set[str] = field(default_factory=set)
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

    def _record_action(
        self,
        action: str,
        *,
        rule_key: str,
        decision: str,
        reason: str | None = None,
        role: str | None = None,
        region: str | None = None,
        samples: list[dict[str, Any]] | None = None,
        **counts: Any,
    ) -> None:
        """Append a unified sidecar action event.

        Every structure/style/render/text action goes through this helper so the
        sidecar carries a consistent ``decision``/``rule_kind``/``rule_key``
        triple on every entry (convergence plan M1a/M2).  ``decision`` is one of
        ``applied`` / ``observed`` / ``rejected`` / ``skipped``.  Extra per-rule
        counters (``pairs``, ``paragraphs``, ``runs`` ...) are forwarded via
        ``counts`` and merged into the payload.
        """

        payload: dict[str, Any] = {
            "action": action,
            "rule_key": rule_key,
            "rule_kind": self.hook_policy.kind(rule_key),
            "decision": decision,
        }
        if reason is not None:
            payload["reason"] = reason
        if role is not None:
            payload["role"] = role
        if region is not None:
            payload["region"] = region
        if samples is not None:
            payload["samples"] = samples
        for key, value in counts.items():
            payload[key] = value
        self.applied_events.append(payload)

    def _emit_observed_plan(
        self,
        action: str,
        *,
        rule_key: str,
        plan: list[dict[str, Any]],
        sample_limit: int = 8,
    ) -> None:
        """Record an ``observe``-mode plan batch without mutating the document.

        Each plan item carries a ``kind`` (``merge`` / ``split`` / ``remove`` /
        ``collapse`` / ``reconcile`` / ``reject``) plus a human-readable
        ``reason`` and the paragraph role(s) involved, so the sidecar explains
        what the rule *would* have done under ``apply``.
        """

        if not plan:
            return
        samples = [
            {k: v for k, v in item.items() if k != "paragraph"}
            for item in plan[:sample_limit]
        ]
        by_kind: dict[str, int] = {}
        for item in plan:
            by_kind[item.get("kind", "unknown")] = by_kind.get(item.get("kind", "unknown"), 0) + 1
        self._record_action(
            action,
            rule_key=rule_key,
            decision="observed",
            samples=samples,
            plan_total=len(plan),
            plan_by_kind=by_kind,
            role_counts=_structure_plan_role_counts(plan),
        )

    def _emit_rejected_plan(
        self,
        action: str,
        *,
        rule_key: str,
        plan: list[dict[str, Any]],
        sample_limit: int = 8,
    ) -> None:
        rejected = [item for item in plan if item.get("guard_decision") == "rejected"]
        if not rejected:
            return
        samples = [
            {k: v for k, v in item.items() if k != "paragraph"}
            for item in rejected[:sample_limit]
        ]
        self._record_action(
            action,
            rule_key=rule_key,
            decision="rejected",
            reason="layout_guard",
            samples=samples,
            plan_total=len(rejected),
            role_counts=_structure_plan_role_counts(rejected),
        )

    def _allowed_plan_items(self, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in plan if item.get("guard_decision") != "rejected"]

    def classify_document(self, document: Any) -> None:
        records = self._collect_records(document)
        self.records_by_id = {record.paragraph_id: record for record in records}
        self.records_by_object_id = {record.object_id: record for record in records}
        self._fallback_line_protected_bands = _detect_fallback_line_underscore_bands(records)
        schematic_label_ids = _detect_schematic_figure_label_ids(records)
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
            if record.paragraph_id in schematic_label_ids:
                _mark(record, "preserved_token", "preserve", 0.96, ("schematic figure fallback label",))
                continue
            if _is_edge_metadata_preserve_candidate(record):
                _mark(record, "preserved_token", "preserve", 0.95, ("edge metadata header/footer",))
                continue
            if _is_preserve_candidate(record):
                _mark(record, "preserved_token", "preserve", 0.97, ("short stable token",))

        self._capture_source_layouts(records)
        self.axis_diagnostics["paragraph_candidates"] = _axis_paragraph_diagnostics(records)
        self._build_toc_alignment(records)
        self._classify_repeated_edge_text(records)
        self._build_page_layout_summaries(records)
        self.note_phase(
            "classify_document",
            {
                "paragraphs": len(records),
                "roles": self._role_counts(),
                "groups": len(self.groups),
                "layout_regions": self._layout_region_counts(),
            },
        )
        self._before_structure_snapshot = self._build_structure_snapshot(document, stage="before_translation")

    def should_skip_translation(self, paragraph: Any) -> bool:
        record = self._record_for_paragraph(paragraph)
        text = str(getattr(paragraph, "unicode", "") or "")
        if record is not None and record.policy == "preserve":
            self._record_action(
                "skip_translation",
                rule_key="skip_translation",
                decision="applied",
                role=record.role,
                paragraph_id=record.paragraph_id,
                policy=record.policy,
            )
            return True
        if not _should_preserve_dynamic_text(text):
            return False
        if record is not None:
            _mark(record, "dynamic_preserve", "preserve", 0.84, ("short numeric/unit axis fragment",))
        self._record_action(
            "skip_translation",
            rule_key="skip_translation",
            decision="applied",
            role=record.role if record is not None else "dynamic_preserve",
            paragraph_id=record.paragraph_id if record is not None else None,
            policy="preserve",
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
        if record.paragraph_id in self._detached_i2c_visual_record_ids:
            text = _detached_i2c_semantic_text(text)
        if record.role != "toc_entry":
            protected_text = self._protect_technical_tokens(record, text)
            return protected_text
        toc_parts = _split_toc_entry(text) or _split_toc_entry(record.text)
        if toc_parts is None:
            return text
        self._record_action(
            "translate_toc_title_only",
            rule_key="translate_toc_title_only",
            decision="applied",
            role=record.role,
            paragraph_id=record.paragraph_id,
            policy=record.policy,
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
            if record.paragraph_id in self._detached_i2c_visual_record_ids:
                translated_text = _detached_i2c_visual_text(translated_text)
            if _has_inline_numbered_markers(record.text):
                translated_text = _strip_babeldoc_style_placeholders(translated_text)
        restored_text = _restore_source_line_breaks(source_text, translated_text)
        if restored_text != translated_text and record is not None:
            self._record_action(
                "restore_source_line_breaks",
                rule_key="restore_source_line_breaks",
                decision="applied",
                role=record.role,
                paragraph_id=record.paragraph_id,
                policy=record.policy,
            )
        return restored_text

    def _protect_technical_tokens(self, record: _ParagraphRecord, text: str) -> str:
        protected_text, protected = _protect_technical_tokens_in_text(text)
        if not protected:
            return text
        self._protected_tokens[record.paragraph_id] = protected
        self._record_action(
            "protect_technical_tokens",
            rule_key="protect_technical_tokens",
            decision="applied",
            role=record.role,
            paragraph_id=record.paragraph_id,
            count=len(protected),
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
            self._record_action(
                "normalize_pdf_font_traits",
                rule_key="normalize_pdf_font_traits",
                decision="applied",
                samples=samples[:8],
                fonts=updated,
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
            self._record_action(
                "restore_neighbor_protected_placeholders",
                rule_key="restore_neighbor_protected_placeholders",
                decision="applied",
                paragraph_id=record.paragraph_id,
                page_number=record.page_number,
                restored=restored_pairs,
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
        self._record_action(
            "restore_definition_line_styles_after_translation",
            rule_key="restore_definition_line_styles_after_translation",
            decision="applied",
            role=record.role,
            paragraph_id=record.paragraph_id,
            layout_label=record.layout_label,
            text=str(getattr(paragraph, "unicode", "") or "")[:180],
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
            self._record_action(
                "restore_vertical_passthrough_layout",
                rule_key="restore_vertical_passthrough_layout",
                decision="applied",
                count=restored,
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
        if source_rect is not None and _is_page_edge_rect(source_rect, page_records):
            return True

        matched_non_axis_records: set[str] = set()
        matched_axis_records: set[str] = set()
        matched_edge_records: set[str] = set()
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
            if _is_edge_band(best_record):
                matched_edge_records.add(best_record.paragraph_id)
                continue
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
        if matched_edge_records:
            return True
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
        rule_key = "collapse_overlap"
        if self.hook_policy.is_off(rule_key):
            return False
        plan = self._plan_collapse_overlap(document)
        if not plan:
            return False
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "collapse_overlapping_same_baseline_fragments_before_translation",
                rule_key=rule_key,
                plan=plan,
            )
            return False
        self._emit_rejected_plan(
            "collapse_overlapping_same_baseline_fragments_before_translation",
            rule_key=rule_key,
            plan=plan,
        )
        return self._apply_collapse_overlap(document, self._allowed_plan_items(plan))

    def _plan_collapse_overlap(self, document: Any) -> list[dict[str, Any]]:
        """Read-only: list overlapping-baseline clusters that would be collapsed.

        The absorb decision reuses the same rect/text helpers as the legacy
        apply path, so observe and apply agree on what gets merged.  Paragraphs
        are linked by ``paragraph_id`` (stable across plan/apply) rather than by
        list index, which would shift once removals start.
        """

        plan: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 3:
                continue
            groups = _group_overlapping_same_baseline_paragraphs(paragraphs)
            if not groups:
                continue
            removed_indices: set[int] = set()
            for group in groups:
                cluster = _build_overlap_collapse_cluster(paragraphs, group, removed_indices)
                if cluster is None:
                    continue
                base_record = self._record_for_paragraph(cluster.base)
                absorbed_records = [
                    self._record_for_paragraph(paragraphs[index])
                    for index in cluster.absorbed_indices
                    if index != cluster.base_index
                ]
                item = {
                    "kind": "collapse",
                    "base_id": base_record.paragraph_id if base_record else None,
                    "role": base_record.role if base_record else "body",
                    "absorbed_ids": [r.paragraph_id for r in absorbed_records if r is not None],
                    "reason": "overlapping_same_baseline_cluster",
                    "before": [str(getattr(paragraph, "unicode", "") or "")[:80] for _index, paragraph in cluster.ordered_group],
                    "after": cluster.merged_text[:160],
                    "rect": cluster.merged_rect,
                }
                item.update(self._guard_collapse_records(base_record, absorbed_records))
                plan.append(item)
                for candidate_index in cluster.absorbed_indices:
                    if candidate_index == cluster.base_index:
                        continue
                    removed_indices.add(candidate_index)
        return plan

    def _apply_collapse_overlap(self, document: Any, plan: list[dict[str, Any]]) -> bool:
        base_ids = {item["base_id"] for item in plan if item.get("base_id")}
        absorbed_ids = {pid for item in plan for pid in item.get("absorbed_ids", [])}
        if not base_ids or not absorbed_ids:
            return False
        collapsed = 0
        samples: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 3:
                continue
            groups = _group_overlapping_same_baseline_paragraphs(paragraphs)
            if not groups:
                continue
            removed_indices: set[int] = set()
            for group in groups:
                cluster = _build_overlap_collapse_cluster(paragraphs, group, removed_indices)
                if cluster is None:
                    continue
                base_record = self._record_for_paragraph(cluster.base)
                if base_record is None or base_record.paragraph_id not in base_ids:
                    continue
                before_texts = [str(getattr(paragraph, "unicode", "") or "")[:80] for _index, paragraph in cluster.ordered_group]
                cluster.base.unicode = cluster.merged_text
                _set_box_rect(getattr(cluster.base, "box", None), cluster.merged_rect)
                _set_plain_unicode_paragraph_text(cluster.base, cluster.merged_text)
                cluster.base.optimal_scale = None
                self._focus_postprocess_paragraph(cluster.base)
                for candidate_index in cluster.absorbed_indices:
                    if candidate_index == cluster.base_index:
                        continue
                    removed_indices.add(candidate_index)
                    collapsed += 1
                if len(samples) < 8 and any(index in removed_indices for index, _paragraph in cluster.ordered_group if index != cluster.base_index):
                    samples.append(
                        {
                            "before": before_texts,
                            "after": str(getattr(cluster.base, "unicode", "") or "")[:160],
                            "rect": _box_rect(getattr(cluster.base, "box", None)),
                        }
                    )
            if removed_indices:
                page.pdf_paragraph = [
                    paragraph
                    for paragraph_index, paragraph in enumerate(paragraphs)
                    if paragraph_index not in removed_indices
                ]
        if collapsed:
            self._record_action(
                "collapse_overlapping_same_baseline_fragments_before_translation",
                rule_key="collapse_overlap",
                decision="applied",
                pairs=collapsed,
                samples=samples,
                role_counts=_structure_plan_role_counts(plan),
            )
        return collapsed > 0

    def normalize_fragmented_paragraphs_before_translation(self, document: Any) -> bool:
        rule_key = "normalize_fragmented"
        if self.hook_policy.is_off(rule_key):
            return False
        plan = self._plan_normalize_fragmented(document)
        if not plan:
            return False
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "split_multiline_paragraphs_before_translation",
                rule_key=rule_key,
                plan=plan,
            )
            return False
        self._emit_rejected_plan(
            "split_multiline_paragraphs_before_translation",
            rule_key=rule_key,
            plan=plan,
        )
        return self._apply_normalize_fragmented(document, self._allowed_plan_items(plan))

    def _plan_normalize_fragmented(self, document: Any) -> list[dict[str, Any]]:
        """Read-only: list every paragraph that would be split into visual lines.

        Only ``fallback_line`` paragraphs are eligible (see
        ``_supports_visual_line_split``).  A real multi-line prose body block is
        explicitly marked ``reason=multiline_body_block`` so observe mode never
        splits ordinary body text (convergence plan M1b §B3).
        """

        return self._plan_observe_multiline_body_blocks(document) + self._plan_split_compact_fallback_labels(document)

    def _plan_observe_multiline_body_blocks(self, document: Any) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            for paragraph in getattr(page, "pdf_paragraph", []) or []:
                if not _supports_visual_line_split(paragraph):
                    continue
                record = self._record_for_paragraph(paragraph)
                rect = _box_rect(getattr(paragraph, "box", None))
                text = str(getattr(paragraph, "unicode", "") or "")
                if rect is None or record is None:
                    continue
                if not _looks_like_multiline_prose_block(paragraph, rect, text):
                    continue
                item = {
                    "kind": "split",
                    "paragraph_id": record.paragraph_id,
                    "role": record.role,
                    "reason": "multiline_body_block",
                    "source": text[:120],
                }
                item.update(self._guard_split_record(record, "multiline_body_block"))
                plan.append(item)
        return plan

    def _plan_split_compact_fallback_labels(self, document: Any) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            for paragraph in getattr(page, "pdf_paragraph", []) or []:
                if not _supports_visual_line_split(paragraph):
                    continue
                record = self._record_for_paragraph(paragraph)
                text = str(getattr(paragraph, "unicode", "") or "")
                parts = _split_paragraph_by_visual_lines(
                    paragraph,
                    symbol_font_ids=self._symbol_font_ids_by_paragraph_object_id.get(id(paragraph), frozenset()),
                )
                if len(parts) <= 1:
                    continue
                item = {
                    "kind": "split",
                    "paragraph_id": record.paragraph_id if record else None,
                    "role": record.role if record else "body",
                    "reason": "fallback_line_visual_split",
                    "source": text[:120],
                    "parts": [str(getattr(part, "unicode", "") or "")[:80] for part in parts],
                }
                item.update(self._guard_split_record(record, "fallback_line_visual_split"))
                plan.append(item)
        return plan

    def _apply_normalize_fragmented(self, document: Any, plan: list[dict[str, Any]]) -> bool:
        eligible_ids = {
            item["paragraph_id"]
            for item in plan
            if item.get("reason") == "fallback_line_visual_split" and item.get("paragraph_id")
        }
        if not eligible_ids:
            return False
        split_lines = 0
        split_samples: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if not paragraphs:
                continue
            rewritten: list[Any] = []
            for paragraph in paragraphs:
                record = self._record_for_paragraph(paragraph)
                if record is None or record.paragraph_id not in eligible_ids:
                    rewritten.append(paragraph)
                    continue
                parts = _split_paragraph_by_visual_lines(
                    paragraph,
                    symbol_font_ids=self._symbol_font_ids_by_paragraph_object_id.get(id(paragraph), frozenset()),
                )
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
            self._record_action(
                "split_multiline_paragraphs_before_translation",
                rule_key="normalize_fragmented",
                decision="applied",
                paragraphs=split_lines,
                samples=split_samples,
                role_counts=_structure_plan_role_counts(
                    [item for item in plan if item.get("paragraph_id") in eligible_ids]
                ),
            )
        return split_lines > 0

    def merge_same_line_fragment_bridges_before_translation(self, document: Any) -> bool:
        rule_key = "merge_same_line_fragment_bridge"
        if self.hook_policy.is_off(rule_key):
            return False
        plan = self._plan_merge_same_line_fragment_bridges(document)
        if not plan:
            return False
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "merge_same_line_fragment_bridges_before_translation",
                rule_key=rule_key,
                plan=plan,
            )
            return False
        self._emit_rejected_plan(
            "merge_same_line_fragment_bridges_before_translation",
            rule_key=rule_key,
            plan=plan,
        )
        return self._apply_merge_same_line_fragment_bridges(document, self._allowed_plan_items(plan))

    def _plan_merge_same_line_fragment_bridges(self, document: Any) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            ordered_items = [
                (paragraph, original_index)
                for original_index, paragraph in enumerate(getattr(page, "pdf_paragraph", []) or [])
            ]
            if len(ordered_items) < 2:
                continue
            ordered_items.sort(key=lambda item: _paragraph_visual_sort_key(item[0], item[1]))
            restore: list[tuple[Any, str, list[Any], Any, tuple[float, float, float, float] | None, Any]] = []
            consumed_indices: set[int] = set()
            index = 0
            while index < len(ordered_items):
                if index in consumed_indices:
                    index += 1
                    continue
                current, _current_original_index = ordered_items[index]
                self._snapshot_for_restore(current, restore)
                while True:
                    candidate_index = self._best_same_line_fragment_bridge_candidate(
                        current,
                        index,
                        ordered_items,
                        consumed_indices,
                    )
                    if candidate_index is None:
                        break
                    right, _right_original_index = ordered_items[candidate_index]
                    decision = self._same_line_fragment_bridge_decision(current, right)
                    if decision is None:
                        break
                    reason, separator = decision
                    plan.append(self._same_line_fragment_bridge_plan_item(current, right, reason))
                    _merge_paragraphs(current, right, separator=separator)
                    consumed_indices.add(candidate_index)
                index += 1
            for paragraph, unicode_value, composition, box, rect, optimal_scale in restore:
                paragraph.unicode = unicode_value
                paragraph.pdf_paragraph_composition = composition
                if box is not None:
                    _set_box_rect(box, rect)
                if optimal_scale is not None:
                    paragraph.optimal_scale = optimal_scale
        return plan

    def _best_same_line_fragment_bridge_candidate(
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
            if candidate_rect is None or candidate_rect[0] < current_rect[0]:
                continue
            decision = self._same_line_fragment_bridge_decision(current, candidate)
            if decision is None:
                continue
            reason, _separator = decision
            guard = self._guard_same_line_fragment_bridge(current, candidate, reason)
            if guard.get("guard_decision") == "rejected":
                continue
            gap = max(candidate_rect[0] - current_rect[2], -1.0)
            priority = 0.0 if reason == "inline_punctuation" else 0.1 if reason == "inline_decimal_continuation" else 1.0
            score = (priority, gap, candidate_rect[0])
            if best is None or score < best[0]:
                best = (score, candidate_index)
        return None if best is None else best[1]

    def _same_line_fragment_bridge_decision(self, left: Any, right: Any) -> tuple[str, str | None] | None:
        if getattr(left, "xobj_id", None) != getattr(right, "xobj_id", None):
            return None
        right_text = str(getattr(right, "unicode", "") or "")
        if _looks_like_dot_leader_fragment(right_text):
            return None
        left_rect = _box_rect(getattr(left, "box", None))
        right_rect = _box_rect(getattr(right, "box", None))
        if left_rect is None or right_rect is None:
            return None
        if self._should_attach_inline_punctuation_fragment(left, right):
            return "inline_punctuation", ""
        if _looks_like_inline_decimal_continuation(left, right):
            return "inline_decimal_continuation", ""
        if _looks_like_inline_broken_word_continuation(
            str(getattr(left, "unicode", "") or ""),
            str(getattr(right, "unicode", "") or ""),
            left_rect,
            right_rect,
        ):
            baseline_ok, _reason = _same_baseline_close_gap(left_rect, right_rect)
            if baseline_ok:
                return "broken_word_continuation", ""
        if _looks_like_inline_micro_fragment_continuation(left, right) and self._has_mixed_region_micro_fragment_context(left, right):
            return "inline_micro_fragment_continuation", ""
        return None

    def _has_mixed_region_micro_fragment_context(self, left: Any, right: Any) -> bool:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        left_region = self._record_layout_region(left_record)
        right_region = self._record_layout_region(right_record)
        if left_record is None or right_record is None or left_region is None or right_region is None:
            return False
        regions = {left_region.region, right_region.region}
        if not regions <= {"body_column", "table", "unknown"}:
            return False
        return "table" in regions or "unknown" in regions

    def _same_line_fragment_bridge_plan_item(self, left: Any, right: Any, reason: str) -> dict[str, Any]:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        item = {
            "kind": "merge",
            "left_id": left_record.paragraph_id if left_record else None,
            "right_id": right_record.paragraph_id if right_record else None,
            "left_role": left_record.role if left_record else "body",
            "right_role": right_record.role if right_record else "body",
            "reason": reason,
            "left": str(getattr(left, "unicode", "") or "")[:80],
            "right": str(getattr(right, "unicode", "") or "")[:80],
            "rect": _box_rect(getattr(left, "box", None)),
        }
        item.update(self._guard_same_line_fragment_bridge(left, right, reason))
        return item

    def _guard_same_line_fragment_bridge(self, left: Any, right: Any, reason: str) -> dict[str, Any]:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        guard = self._guard_merge_records(left_record, right_record)
        if guard.get("guard_decision") == "allowed":
            return guard
        if reason not in {
            "inline_punctuation",
            "inline_decimal_continuation",
            "broken_word_continuation",
            "inline_micro_fragment_continuation",
        }:
            return guard
        left_region = self._record_layout_region(left_record)
        right_region = self._record_layout_region(right_record)
        if left_record is None or right_record is None or left_region is None or right_region is None:
            return guard
        left_rect = _box_rect(getattr(left, "box", None))
        right_rect = _box_rect(getattr(right, "box", None))
        if left_rect is None or right_rect is None:
            return guard
        baseline_ok, _baseline_reason = _same_baseline_close_gap(left_rect, right_rect)
        if not baseline_ok:
            return guard
        if (
            guard.get("guard_reason") == "unknown_region"
            and left_region.region == "body_column"
            and right_region.region == "unknown"
            and right_record.role in {"body", "preserved_token"}
        ):
            return guard | {"guard_decision": "allowed", "guard_reason": "same_body_column_inline_bridge"}
        if (
            reason == "broken_word_continuation"
            and guard.get("guard_reason") == "cross_column"
            and left_region.region == "body_column"
            and right_region.region == "body_column"
            and _is_tight_inline_join(left_rect, right_rect)
        ):
            return guard | {"guard_decision": "allowed", "guard_reason": "tight_inline_column_boundary_bridge"}
        if (
            guard.get("guard_reason") in {"non_body_region", "unknown_region"}
            and left_region.region in {"body_column", "table", "unknown"}
            and right_region.region in {"body_column", "table", "unknown"}
            and _looks_like_inline_micro_fragment_continuation(left, right)
        ):
            return guard | {"guard_decision": "allowed", "guard_reason": "dense_same_line_micro_fragment_bridge"}
        if self._looks_like_safe_mixed_region_same_line_continuation(left, right):
            return guard | {"guard_decision": "allowed", "guard_reason": "mixed_region_same_line_text_continuation"}
        return guard

    def _looks_like_safe_mixed_region_same_line_continuation(self, left: Any, right: Any) -> bool:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        left_region = self._record_layout_region(left_record)
        right_region = self._record_layout_region(right_record)
        if left_record is None or right_record is None or left_region is None or right_region is None:
            return False
        if left_record.role != "body" or right_record.role != "body":
            return False
        if {left_region.region, right_region.region} != {"body_column", "table"}:
            return False
        if left_record.page_number != right_record.page_number or left_record.xobj_id != right_record.xobj_id:
            return False
        left_rect = _box_rect(getattr(left, "box", None))
        right_rect = _box_rect(getattr(right, "box", None))
        if left_rect is None or right_rect is None:
            return False
        baseline_ok, _baseline_reason = _same_baseline_close_gap(left_rect, right_rect)
        if not baseline_ok:
            return False
        return _looks_like_same_line_text_continuation(left, right)

    def _apply_merge_same_line_fragment_bridges(self, document: Any, plan: list[dict[str, Any]]) -> bool:
        allowed_pairs = {
            (item.get("left_id"), item.get("right_id"))
            for item in plan
            if item.get("left_id") and item.get("right_id")
        }
        plan_by_pair = {
            (item.get("left_id"), item.get("right_id")): item
            for item in plan
            if item.get("left_id") and item.get("right_id")
        }
        if not allowed_pairs:
            return False
        merged = 0
        samples: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            ordered_items = [
                (paragraph, original_index)
                for original_index, paragraph in enumerate(getattr(page, "pdf_paragraph", []) or [])
            ]
            if len(ordered_items) < 2:
                continue
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
                    candidate_index = self._best_same_line_fragment_bridge_candidate(
                        current,
                        index,
                        ordered_items,
                        consumed_indices,
                    )
                    if candidate_index is None:
                        break
                    right, right_original_index = ordered_items[candidate_index]
                    left_record = self._record_for_paragraph(current)
                    right_record = self._record_for_paragraph(right)
                    pair_key = (
                        left_record.paragraph_id if left_record else None,
                        right_record.paragraph_id if right_record else None,
                    )
                    if pair_key not in allowed_pairs:
                        break
                    decision = self._same_line_fragment_bridge_decision(current, right)
                    if decision is None:
                        break
                    _reason, separator = decision
                    if len(samples) < 8:
                        samples.append(dict(plan_by_pair.get(pair_key) or _same_line_merge_sample(current, right)))
                    _merge_paragraphs(current, right, separator=separator)
                    self._focus_postprocess_paragraph(current)
                    merged_original_indices.append(right_original_index)
                    consumed_indices.add(candidate_index)
                    merged += 1
                rewritten.append((min(merged_original_indices), current))
                index += 1
            rewritten.sort(key=lambda item: item[0])
            page.pdf_paragraph = [paragraph for _original_index, paragraph in rewritten]
        if merged:
            self._record_action(
                "merge_same_line_fragment_bridges_before_translation",
                rule_key="merge_same_line_fragment_bridge",
                decision="applied",
                pairs=merged,
                samples=samples,
                role_counts=_structure_plan_role_counts(plan),
            )
        return merged > 0

    def merge_contiguous_body_lines_before_translation(self, document: Any) -> bool:
        rule_key = "merge_contiguous_body_lines"
        if self.hook_policy.is_off(rule_key):
            return False
        plan = self._plan_merge_contiguous_body_lines(document)
        if not plan:
            return False
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "merge_contiguous_body_lines_before_translation",
                rule_key=rule_key,
                plan=plan,
            )
            return False
        self._emit_rejected_plan(
            "merge_contiguous_body_lines_before_translation",
            rule_key=rule_key,
            plan=plan,
        )
        return self._apply_merge_contiguous_body_lines(document, self._allowed_plan_items(plan))

    def _plan_merge_contiguous_body_lines(self, document: Any) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 2:
                continue
            ordered_items = [
                (paragraph, original_index)
                for original_index, paragraph in enumerate(paragraphs)
            ]
            ordered_items.sort(key=lambda item: _paragraph_visual_sort_key(item[0], item[1]))
            restore: list[tuple[Any, str, list[Any], Any, tuple[float, float, float, float] | None, Any]] = []
            consumed_indices: set[int] = set()
            index = 0
            while index < len(ordered_items):
                if index in consumed_indices:
                    index += 1
                    continue
                current, _current_original_index = ordered_items[index]
                self._snapshot_for_restore(current, restore)
                while True:
                    candidate_index = self._best_contiguous_body_line_candidate(
                        current,
                        index,
                        ordered_items,
                        consumed_indices,
                    )
                    if candidate_index is None:
                        break
                    right, _right_original_index = ordered_items[candidate_index]
                    item = self._contiguous_body_line_plan_item(current, right)
                    plan.append(item)
                    if item.get("guard_decision") == "rejected":
                        break
                    _merge_paragraphs(current, right, separator=" ")
                    consumed_indices.add(candidate_index)
                index += 1
            for paragraph, unicode_value, composition, box, rect, optimal_scale in restore:
                paragraph.unicode = unicode_value
                paragraph.pdf_paragraph_composition = composition
                if box is not None:
                    _set_box_rect(box, rect)
                if optimal_scale is not None:
                    paragraph.optimal_scale = optimal_scale
        return plan

    def _best_contiguous_body_line_candidate(
        self,
        current: Any,
        current_index: int,
        ordered_items: list[tuple[Any, int]],
        consumed_indices: set[int],
    ) -> int | None:
        current_rect = _box_rect(getattr(current, "box", None))
        if current_rect is None:
            return None
        best: tuple[tuple[float, float], int] | None = None
        for candidate_index, (candidate, _candidate_original_index) in enumerate(ordered_items):
            if candidate_index == current_index or candidate_index in consumed_indices:
                continue
            candidate_rect = _box_rect(getattr(candidate, "box", None))
            if candidate_rect is None:
                continue
            if not self._should_merge_contiguous_body_lines(current, candidate):
                continue
            vertical_gap = current_rect[1] - candidate_rect[3]
            score = (abs(vertical_gap), candidate_rect[0])
            if best is None or score < best[0]:
                best = (score, candidate_index)
        return None if best is None else best[1]

    def _should_merge_contiguous_body_lines(self, left: Any, right: Any) -> bool:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        if left_record is None or right_record is None:
            return False
        if left_record.role != "body" or right_record.role != "body":
            return False
        if left_record.layout_label != "plain text" or right_record.layout_label != "plain text":
            return False
        if left_record.page_number != right_record.page_number or left_record.xobj_id != right_record.xobj_id:
            return False
        left_region = self._record_layout_region(left_record)
        right_region = self._record_layout_region(right_record)
        if (
            left_region is None
            or right_region is None
            or left_region.region != "body_column"
            or right_region.region != "body_column"
            or left_region.column_id != right_region.column_id
        ):
            return False
        left_rect = _box_rect(getattr(left, "box", None))
        right_rect = _box_rect(getattr(right, "box", None))
        if left_rect is None or right_rect is None:
            return False
        return _looks_like_contiguous_body_line_pair(
            str(getattr(left, "unicode", "") or ""),
            str(getattr(right, "unicode", "") or ""),
            left_rect,
            right_rect,
        )

    def _contiguous_body_line_plan_item(self, left: Any, right: Any) -> dict[str, Any]:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        item = {
            "kind": "merge",
            "left_id": left_record.paragraph_id if left_record else None,
            "right_id": right_record.paragraph_id if right_record else None,
            "left_role": left_record.role if left_record else "body",
            "right_role": right_record.role if right_record else "body",
            "reason": "contiguous_body_line",
            "left": str(getattr(left, "unicode", "") or "")[:80],
            "right": str(getattr(right, "unicode", "") or "")[:80],
            "rect": _box_rect(getattr(left, "box", None)),
        }
        item.update(self._guard_merge_records(left_record, right_record))
        return item

    def _apply_merge_contiguous_body_lines(self, document: Any, plan: list[dict[str, Any]]) -> bool:
        allowed_pairs = {
            (item.get("left_id"), item.get("right_id"))
            for item in plan
            if item.get("left_id") and item.get("right_id")
        }
        if not allowed_pairs:
            return False
        merged = 0
        samples: list[dict[str, Any]] = []
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
                    candidate_index = self._best_contiguous_body_line_candidate(
                        current,
                        index,
                        ordered_items,
                        consumed_indices,
                    )
                    if candidate_index is None:
                        break
                    right, right_original_index = ordered_items[candidate_index]
                    left_record = self._record_for_paragraph(current)
                    right_record = self._record_for_paragraph(right)
                    pair_key = (
                        left_record.paragraph_id if left_record else None,
                        right_record.paragraph_id if right_record else None,
                    )
                    if pair_key not in allowed_pairs:
                        break
                    if len(samples) < 8:
                        samples.append(_same_line_merge_sample(current, right))
                    _merge_paragraphs(current, right, separator=" ")
                    self._focus_postprocess_paragraph(current)
                    merged_original_indices.append(right_original_index)
                    consumed_indices.add(candidate_index)
                    merged += 1
                rewritten.append((min(merged_original_indices), current))
                index += 1
            rewritten.sort(key=lambda item: item[0])
            page.pdf_paragraph = [paragraph for _original_index, paragraph in rewritten]
        if merged:
            self._record_action(
                "merge_contiguous_body_lines_before_translation",
                rule_key="merge_contiguous_body_lines",
                decision="applied",
                pairs=merged,
                samples=samples,
                role_counts=_structure_plan_role_counts(plan),
            )
        return merged > 0

    def split_wrapped_same_line_tails_before_translation(self, document: Any) -> bool:
        rule_key = "split_wrapped_same_line_tail"
        if self.hook_policy.is_off(rule_key):
            return False
        plan = self._plan_split_wrapped_same_line_tails(document)
        if not plan:
            return False
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "split_wrapped_same_line_tail_before_translation",
                rule_key=rule_key,
                plan=plan,
            )
            return False
        self._emit_rejected_plan(
            "split_wrapped_same_line_tail_before_translation",
            rule_key=rule_key,
            plan=plan,
        )
        return self._apply_split_wrapped_same_line_tails(document, self._allowed_plan_items(plan))

    def _plan_split_wrapped_same_line_tails(self, document: Any) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 2:
                continue
            ordered_items = [
                (paragraph, original_index)
                for original_index, paragraph in enumerate(paragraphs)
            ]
            ordered_items.sort(key=lambda item: _paragraph_visual_sort_key(item[0], item[1]))
            for right, _right_original_index in ordered_items:
                right_record = self._record_for_paragraph(right)
                if right_record is None or right_record.role != "body":
                    continue
                groups = _wrapped_same_line_tail_groups(right)
                if groups is None:
                    continue
                first_group_rect = groups[0][1]
                first_group_text = _composition_text(groups[0][0]).strip()
                left = _best_wrapped_same_line_tail_left_neighbor(
                    right,
                    first_group_rect,
                    first_group_text,
                    ordered_items,
                    self,
                )
                if left is None:
                    continue
                left_record = self._record_for_paragraph(left)
                guard = self._guard_merge_records(left_record, right_record)
                item = {
                    "kind": "split",
                    "paragraph_id": right_record.paragraph_id,
                    "left_id": left_record.paragraph_id if left_record else None,
                    "role": right_record.role,
                    "left_role": left_record.role if left_record else "unknown",
                    "reason": "wrapped_same_line_tail",
                    "left": str(getattr(left, "unicode", "") or "")[:80],
                    "source": str(getattr(right, "unicode", "") or "")[:120],
                    "parts": [_composition_text(group).strip()[:80] for group, _rect in groups],
                    "first_line_rect": first_group_rect,
                    "source_rect": _box_rect(getattr(right, "box", None)),
                }
                item.update(guard)
                plan.append(item)
        return plan

    def _apply_split_wrapped_same_line_tails(self, document: Any, plan: list[dict[str, Any]]) -> bool:
        eligible_ids = {item["paragraph_id"] for item in plan if item.get("paragraph_id")}
        if not eligible_ids:
            return False
        split_count = 0
        samples: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if not paragraphs:
                continue
            rewritten: list[Any] = []
            for paragraph in paragraphs:
                record = self._record_for_paragraph(paragraph)
                if record is None or record.paragraph_id not in eligible_ids:
                    rewritten.append(paragraph)
                    continue
                parts = _split_paragraph_by_composition_groups(paragraph, _wrapped_same_line_tail_groups(paragraph))
                if len(parts) <= 1:
                    rewritten.append(paragraph)
                    continue
                merged_left = _pop_merge_left_neighbor_for_wrapped_tail(
                    rewritten,
                    parts[0],
                    self,
                )
                if merged_left is not None:
                    rewritten.append(merged_left)
                    rewritten.extend(parts[1:])
                else:
                    rewritten.extend(parts)
                for part in parts:
                    self._focus_postprocess_paragraph(part)
                split_count += len(parts) - 1
                if len(samples) < 8:
                    samples.append(
                        {
                            "source": str(getattr(paragraph, "unicode", "") or "")[:120],
                            "parts": [str(getattr(part, "unicode", "") or "")[:80] for part in parts],
                            "merged_left": merged_left is not None,
                        }
                    )
            page.pdf_paragraph = rewritten
        if split_count:
            self._record_action(
                "split_wrapped_same_line_tail_before_translation",
                rule_key="split_wrapped_same_line_tail",
                decision="applied",
                paragraphs=split_count,
                samples=samples,
                role_counts=_structure_plan_role_counts(plan),
            )
        return split_count > 0

    def remove_subsumed_same_line_duplicates_before_translation(self, document: Any) -> bool:
        rule_key = "remove_subsumed"
        if self.hook_policy.is_off(rule_key):
            return False
        plan = self._plan_remove_subsumed(document)
        if not plan:
            return False
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "remove_subsumed_same_line_duplicates_before_translation",
                rule_key=rule_key,
                plan=plan,
            )
            return False
        self._emit_rejected_plan(
            "remove_subsumed_same_line_duplicates_before_translation",
            rule_key=rule_key,
            plan=plan,
        )
        return self._apply_remove_subsumed(document, self._allowed_plan_items(plan))

    def _plan_remove_subsumed(self, document: Any) -> list[dict[str, Any]]:
        """Read-only: list candidate/anchor duplicate pairs that would be removed."""

        plan: list[dict[str, Any]] = []
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
                candidate_record = self._record_for_paragraph(candidate)
                anchor_record = self._record_for_paragraph(paragraphs[anchor_index])
                item = {
                    "kind": "remove",
                    "candidate_id": candidate_record.paragraph_id if candidate_record else None,
                    "anchor_id": anchor_record.paragraph_id if anchor_record else None,
                    "role": (candidate_record.role if candidate_record else "body"),
                    "reason": "subsumed_same_line_duplicate",
                    "anchor": str(getattr(paragraphs[anchor_index], "unicode", "") or "")[:120],
                    "duplicate": str(getattr(candidate, "unicode", "") or "")[:120],
                    "rect": _box_rect(getattr(candidate, "box", None)),
                }
                item.update(self._guard_remove_records(candidate_record, anchor_record))
                plan.append(item)
        return plan

    def _apply_remove_subsumed(self, document: Any, plan: list[dict[str, Any]]) -> bool:
        candidate_ids = {item["candidate_id"] for item in plan if item.get("candidate_id")}
        if not candidate_ids:
            return False
        removed = 0
        samples: list[dict[str, Any]] = []
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
                record = self._record_for_paragraph(candidate)
                if record is None or record.paragraph_id not in candidate_ids:
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
            self._record_action(
                "remove_subsumed_same_line_duplicates_before_translation",
                rule_key="remove_subsumed",
                decision="applied",
                paragraphs=removed,
                samples=samples,
                role_counts=_structure_plan_role_counts(plan),
            )
        return removed > 0

    def merge_same_line_fragments_before_translation(self, document: Any) -> bool:
        rule_key = "merge_same_line"
        if self.hook_policy.is_off(rule_key):
            return False
        plan, rejected = self._plan_merge_same_line(document)
        if not plan and not rejected:
            return False
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "merge_same_line_fragments_before_translation",
                rule_key=rule_key,
                plan=plan,
            )
            if rejected:
                self._record_action(
                    "reject_same_line_fragment_merge",
                    rule_key=rule_key,
                    decision="rejected",
                    samples=rejected,
                    role_counts=_structure_plan_role_counts(rejected),
                )
            return False
        self._emit_rejected_plan(
            "merge_same_line_fragments_before_translation",
            rule_key=rule_key,
            plan=plan,
        )
        return self._apply_merge_same_line(document, self._allowed_plan_items(plan), rejected)

    def _plan_merge_same_line(self, document: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read-only simulation of the same-line merge pass.

        To stay consistent with the apply path, candidate decisions are computed
        against the *accumulated* left state (merge grows ``current.unicode``
        and its box rect).  We patch ``current`` in place while walking a page
        and restore every touched attribute from a saved snapshot at the end, so
        the document is left byte-identical.  Rejected near-miss pairs are also
        captured for the sidecar.
        """

        plan: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 2:
                continue
            ordered_items = [
                (paragraph, original_index)
                for original_index, paragraph in enumerate(paragraphs)
            ]
            ordered_items.sort(key=lambda item: _paragraph_visual_sort_key(item[0], item[1]))
            # Track per-paragraph mutated state so we can restore it after planning.
            restore: list[tuple[Any, str, Any, tuple[float, float, float, float] | None, Any]] = []
            consumed_indices: set[int] = set()
            index = 0
            while index < len(ordered_items):
                if index in consumed_indices:
                    index += 1
                    continue
                current, _current_original_index = ordered_items[index]
                self._snapshot_for_restore(current, restore)
                while True:
                    candidate_index = self._best_merge_continuation_candidate(
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
                                and len(rejected) < 12
                                and _looks_like_potential_same_line_fragment_pair(current, right)
                            ):
                                rejected.append(self._same_line_neighbor_reject_sample(current, right, reason))
                        break
                    right, right_original_index = ordered_items[candidate_index]
                    is_punct = self._should_attach_inline_punctuation_fragment(current, right)
                    should_merge, reason = (True, "inline_punctuation") if is_punct else self._should_merge_same_line_fragments(current, right)
                    plan.append(self._same_line_merge_plan_item(current, right, reason if not is_punct else "inline_punctuation"))
                    # Simulate the merge on current so the next candidate sees accumulated state.
                    if is_punct:
                        _merge_paragraphs(current, right, separator="")
                    elif should_merge:
                        _merge_paragraphs(current, right)
                    else:
                        _merge_paragraphs(current, right, separator="")
                    consumed_indices.add(candidate_index)
                index += 1
            # Restore every paragraph we patched so the document is unchanged.
            for paragraph, unicode_value, composition, box, rect, optimal_scale in restore:
                paragraph.unicode = unicode_value
                paragraph.pdf_paragraph_composition = composition
                if box is not None:
                    _set_box_rect(box, rect)
                if optimal_scale is not None:
                    paragraph.optimal_scale = optimal_scale
        return plan, rejected

    def _snapshot_for_restore(
        self,
        paragraph: Any,
        restore: list[tuple[Any, str, list[Any], Any, tuple[float, float, float, float] | None, Any]],
    ) -> None:
        """Remember a paragraph's mutable state so observe planning can restore it."""

        box = getattr(paragraph, "box", None)
        restore.append(
            (
                paragraph,
                str(getattr(paragraph, "unicode", "") or ""),
                list(getattr(paragraph, "pdf_paragraph_composition", []) or []),
                box,
                _box_rect(box),
                getattr(paragraph, "optimal_scale", None),
            )
        )

    def _same_line_neighbor_reject_sample(self, left: Any, right: Any, reason: str) -> dict[str, Any]:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        item = {
            "left": str(getattr(left, "unicode", "") or "")[:120],
            "right": str(getattr(right, "unicode", "") or "")[:120],
            "left_role": left_record.role if left_record else "unknown",
            "right_role": right_record.role if right_record else "unknown",
            "left_rect": _box_rect(getattr(left, "box", None)),
            "right_rect": _box_rect(getattr(right, "box", None)),
            "reason": reason,
        }
        item.update(self._guard_merge_records(left_record, right_record))
        return item

    def _same_line_merge_plan_item(self, left: Any, right: Any, reason: str) -> dict[str, Any]:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        item = {
            "kind": "merge",
            "left_id": left_record.paragraph_id if left_record else None,
            "right_id": right_record.paragraph_id if right_record else None,
            "left_role": left_record.role if left_record else "body",
            "right_role": right_record.role if right_record else "body",
            "reason": reason,
            "left": str(getattr(left, "unicode", "") or "")[:80],
            "right": str(getattr(right, "unicode", "") or "")[:80],
            "rect": _box_rect(getattr(left, "box", None)),
        }
        item.update(self._guard_merge_records(left_record, right_record))
        return item

    def _apply_merge_same_line(
        self,
        document: Any,
        plan: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
    ) -> bool:
        if not plan:
            return False
        allowed_pairs = {
            (item.get("left_id"), item.get("right_id"))
            for item in plan
            if item.get("left_id") and item.get("right_id")
        }
        if not allowed_pairs:
            return False
        # Re-run the real merge pass.  We do not replay ``plan`` item-by-item
        # because the live ``current`` accumulates merged text/composition during
        # the walk, and the candidate helpers already encode the same decisions.
        # ``plan`` is only used as the apply/observe contract; the apply path
        # reproduces it deterministically via the same helpers.
        merged = 0
        samples: list[dict[str, Any]] = []
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
                    candidate_index = self._best_merge_continuation_candidate(
                        current,
                        index,
                        ordered_items,
                        consumed_indices,
                    )
                    if candidate_index is None:
                        break
                    right, right_original_index = ordered_items[candidate_index]
                    left_record = self._record_for_paragraph(current)
                    right_record = self._record_for_paragraph(right)
                    pair_key = (
                        left_record.paragraph_id if left_record else None,
                        right_record.paragraph_id if right_record else None,
                    )
                    if pair_key not in allowed_pairs:
                        break
                    sample = _same_line_merge_sample(current, right)
                    if self._should_attach_inline_punctuation_fragment(current, right):
                        if len(samples) < 8:
                            samples.append(sample)
                        _merge_paragraphs(current, right, separator="")
                        self._focus_postprocess_paragraph(current)
                        merged_original_indices.append(right_original_index)
                        consumed_indices.add(candidate_index)
                        merged += 1
                        continue
                    should_merge, _reason = self._should_merge_same_line_fragments(current, right)
                    if should_merge:
                        if len(samples) < 8:
                            samples.append(sample)
                        _merge_paragraphs(current, right)
                    else:
                        if len(samples) < 8:
                            samples.append(sample)
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
            self._record_action(
                "merge_same_line_fragments_before_translation",
                rule_key="merge_same_line",
                decision="applied",
                pairs=merged,
                samples=samples,
                role_counts=_structure_plan_role_counts(plan),
            )
        if rejected:
            self._record_action(
                "reject_same_line_fragment_merge",
                rule_key="merge_same_line",
                decision="rejected",
                samples=rejected,
                role_counts=_structure_plan_role_counts(rejected),
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
        if _looks_like_multiline_prose_block(left, left_rect, left_text) and _looks_like_multiline_prose_block(
            right, right_rect, right_text
        ):
            return False, "multi_line_blocks"
        baseline_ok, reason = _same_baseline_close_gap(left_rect, right_rect)
        if not baseline_ok:
            return False, reason
        return True, "ok"

    def _best_merge_continuation_candidate(
        self,
        current: Any,
        current_index: int,
        ordered_items: list[tuple[Any, int]],
        consumed_indices: set[int],
    ) -> int | None:
        candidate_index = self._best_same_line_fragment_candidate(
            current,
            current_index,
            ordered_items,
            consumed_indices,
        )
        if candidate_index is not None:
            return candidate_index
        return self._best_wrapped_decimal_continuation_candidate(
            current,
            current_index,
            ordered_items,
            consumed_indices,
        )

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
        rule_key = "split_numbered_lists"
        if self.hook_policy.is_off(rule_key):
            return
        plan = self._plan_split_numbered_lists(document)
        if not plan:
            return
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "split_numbered_paragraph_before_typesetting",
                rule_key=rule_key,
                plan=plan,
            )
            return
        self._emit_rejected_plan(
            "split_numbered_paragraph_before_typesetting",
            rule_key=rule_key,
            plan=plan,
        )
        self._apply_split_numbered_lists(document, self._allowed_plan_items(plan))

    def _plan_split_numbered_lists(self, document: Any) -> list[dict[str, Any]]:
        """Read-only: list numbered paragraphs that would be split by line marker.

        Runs in the ``Typesetting`` stage (after translation) but obeys the same
        structure policy as the pre-translation rules, per the convergence plan
        (§现状校正-2 / §第二阶段-2): a translation-time split cannot bypass the
        layout guard.
        """

        plan: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            for paragraph in getattr(page, "pdf_paragraph", []) or []:
                record = self._record_for_paragraph(paragraph)
                if record is None or not _has_inline_numbered_markers(record.text):
                    continue
                lines = [line.strip() for line in str(getattr(paragraph, "unicode", "") or "").splitlines() if line.strip()]
                if len(lines) < 2:
                    continue
                item = {
                    "kind": "split",
                    "paragraph_id": record.paragraph_id,
                    "role": record.role,
                    "reason": "inline_numbered_markers",
                    "lines": lines[:8],
                }
                item.update(self._guard_split_record(record, "inline_numbered_markers"))
                plan.append(item)
        return plan

    def _apply_split_numbered_lists(self, document: Any, plan: list[dict[str, Any]]) -> None:
        eligible_ids = {item["paragraph_id"] for item in plan if item.get("paragraph_id")}
        if not eligible_ids:
            return
        split_count = 0
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if not paragraphs:
                continue
            rewritten = []
            for paragraph in paragraphs:
                record = self._record_for_paragraph(paragraph)
                if record is None or record.paragraph_id not in eligible_ids:
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
            self._record_action(
                "split_numbered_paragraph_before_typesetting",
                rule_key="split_numbered_lists",
                decision="applied",
                paragraphs=split_count,
                role_counts=_structure_plan_role_counts(plan),
            )

    def normalize_body_font_sizes_before_typesetting(self, document: Any) -> None:
        if not self.hook_policy.is_apply("normalize_body_font_sizes"):
            return
        normalized_runs = 0
        samples: list[dict[str, Any]] = []
        for page in getattr(document, "page", []) or []:
            for paragraph in getattr(page, "pdf_paragraph", []) or []:
                record = self._record_for_paragraph(paragraph)
                if record is None or record.role != "body" or record.policy != "pass_through":
                    continue
                region = self._record_layout_region(record)
                is_scoped = (
                    self._needs_scoped_postprocess(paragraph)
                    or id(paragraph) in self._definition_style_restored_paragraph_ids
                )
                if not is_scoped and (region is None or region.region != "body_column"):
                    continue
                base_size = _body_paragraph_reference_font_size(paragraph)
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
            self._record_action(
                "normalize_body_font_sizes_before_typesetting",
                rule_key="normalize_body_font_sizes",
                decision="applied",
                runs=normalized_runs,
                samples=samples,
            )

    def normalize_body_scales_before_render(self, page: Any) -> None:
        if not self.hook_policy.is_apply("normalize_body_font_sizes"):
            return
        groups: dict[tuple[int, float], list[tuple[Any, _ParagraphRecord, float | None, int]]] = {}
        lanes: list[dict[str, Any]] = []
        for paragraph in getattr(page, "pdf_paragraph", []) or []:
            record = self._record_for_paragraph(paragraph)
            if record is None or record.role != "body" or record.policy != "pass_through":
                continue
            region = self._record_layout_region(record)
            if region is None or region.region != "body_column":
                continue
            raw_scale = getattr(paragraph, "optimal_scale", None)
            scale = float(raw_scale) if raw_scale is not None and float(raw_scale) > 0 else None
            base_size = _body_paragraph_reference_font_size(paragraph)
            if base_size < 7.0 or base_size > 12.0:
                continue
            text = _paragraph_plain_text(paragraph)
            text_width = _display_width(text)
            if text_width < _BODY_SCALE_NORMALIZATION_MIN_TEXT_WIDTH or not _looks_like_translated_prose_segment(text):
                continue
            lane_id = _body_scale_lane_id(paragraph, lanes)
            groups.setdefault((lane_id, round(base_size * 2.0) / 2.0), []).append((paragraph, record, scale, text_width))

        normalized = 0
        samples: list[dict[str, Any]] = []
        for (lane_id, base_size), entries in groups.items():
            anchor_entries = [
                (paragraph, record, scale)
                for paragraph, record, scale, text_width in entries
                if scale is not None and text_width >= _BODY_SCALE_NORMALIZATION_ANCHOR_TEXT_WIDTH
            ]
            if len(anchor_entries) < _BODY_SCALE_NORMALIZATION_MIN_GROUP_SIZE:
                continue
            scales = sorted(scale for _paragraph, _record, scale in anchor_entries if scale is not None)
            target_scale = min(_BODY_SCALE_NORMALIZATION_MAX_TARGET, _quantile(scales, 0.35))
            target_size = base_size * target_scale
            for paragraph, record, scale, _text_width in entries:
                if scale is not None and scale <= _BODY_SCALE_NORMALIZATION_MIN_SCALE:
                    continue
                current_scale = scale if scale is not None else 1.0
                changed_styles = _apply_body_target_font_size(paragraph, target_size)
                force_retypeset = _force_body_retypeset_with_target_font_size(paragraph, target_size)
                if (
                    not changed_styles
                    and not force_retypeset
                    and abs(current_scale - target_scale) < _BODY_SCALE_NORMALIZATION_MIN_DELTA
                ):
                    continue
                paragraph.optimal_scale = 1.0
                normalized += 1
                if len(samples) < 8:
                    samples.append(
                        {
                            "paragraph_id": record.paragraph_id,
                            "page_number": record.page_number,
                            "lane_id": lane_id,
                            "base_size": round(base_size, 3),
                            "from": round(current_scale, 3),
                            "to": round(target_scale, 3),
                            "target_size": round(target_size, 3),
                            "text": _paragraph_plain_text(paragraph)[:100],
                        }
                    )
        if normalized:
            self._record_action(
                "normalize_body_scales_before_render",
                rule_key="normalize_body_font_sizes",
                decision="applied",
                paragraphs=normalized,
                samples=samples,
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
        raw_page_number = getattr(page, "page_number", None)
        page_number = raw_page_number + 1 if isinstance(raw_page_number, int) else raw_page_number
        tick_groups = _page_level_axis_tick_groups(chars, self.records_by_id.values(), page_number)
        if not groups and not tick_groups:
            return render_units

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

        tick_diagnostics = []
        for group in tick_groups:
            unit = _AxisLabelRenderUnit.from_group(group, sort_mode="y")
            if unit is None:
                continue
            source_char_ids.update(id(char) for char in group)
            replacement_units.append(unit)
            tick_diagnostics.append(
                {
                    "page_number": page_number,
                    "text": _char_group_text(group),
                    "rect": _char_group_rect(group),
                    "characters": len(group),
                    "replacement": "grouped_axis_tick_rotated_text",
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
        self.axis_diagnostics["character_groups"].extend(tick_diagnostics[:24])
        samples = [
            {
                "text": entry["text"][:80],
                "translated_text": entry["translated_text"][:80],
                "rect": entry["rect"],
                "characters": entry["characters"],
            }
            for entry in diagnostics[:8]
        ]
        samples.extend(
            {
                "text": entry["text"][:80],
                "translated_text": entry["text"][:80],
                "rect": entry["rect"],
                "characters": entry["characters"],
            }
            for entry in tick_diagnostics[:8]
        )
        self._record_action(
            "replace_page_axis_label_render_units",
            rule_key="render_axis_label",
            decision="applied",
            page_number=page_number,
            groups=len(replacement_units),
            characters=sum(entry["characters"] for entry in diagnostics) + sum(
                entry["characters"] for entry in tick_diagnostics
            ),
            samples=samples,
        )
        return replaced_units

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
        rule_key = "reconcile_repeated_edge"
        plan: list[dict[str, Any]] = []
        for group_id, paragraph_ids in self.groups.items():
            leader_id = self._translated_leader_id(paragraph_ids)
            if leader_id is None:
                continue
            leader_snapshot = self._translations[leader_id]
            follower_ids: list[str] = []
            for paragraph_id in paragraph_ids:
                if paragraph_id == leader_id:
                    continue
                paragraph = self.paragraphs_by_id.get(paragraph_id)
                record = self.records_by_id.get(paragraph_id)
                if paragraph is None or record is None:
                    continue
                follower_ids.append(paragraph_id)
            if follower_ids:
                plan.append(
                    {
                        "kind": "reconcile",
                        "group_id": group_id,
                        "leader_id": leader_id,
                        "follower_ids": follower_ids,
                        "role": "running_edge_text",
                        "reason": "repeated_edge_leader_sync",
                    }
                )
        if not plan:
            return
        if self.hook_policy.is_off(rule_key):
            return
        if self.hook_policy.is_observe(rule_key):
            self._emit_observed_plan(
                "reconcile_repeated_edge_text",
                rule_key=rule_key,
                plan=plan,
            )
            return
        # apply
        changed_total = 0
        for item in plan:
            leader_snapshot = self._translations.get(item["leader_id"])
            if leader_snapshot is None:
                continue
            changed = 0
            for paragraph_id in item["follower_ids"]:
                paragraph = self.paragraphs_by_id.get(paragraph_id)
                if paragraph is None:
                    continue
                paragraph.unicode = leader_snapshot.unicode
                paragraph.pdf_paragraph_composition = copy.deepcopy(leader_snapshot.composition)
                changed += 1
            if changed:
                self._record_action(
                    "reconcile_repeated_edge_text",
                    rule_key=rule_key,
                    decision="applied",
                    role="running_edge_text",
                    group_id=item["group_id"],
                    leader_id=item["leader_id"],
                    followers=changed,
                    role_counts={"running_edge_text": changed},
                )
                changed_total += changed
        return

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
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "strategy": "babeldoc_internal_hooks_v1",
            "hook_policy": self.hook_policy.to_summary(),
            "counts": self._role_counts(),
            "roles": roles,
            "groups": self.groups,
            "layout_summaries": self._layout_summaries_payload(),
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
                layout_region = self.layout_regions_by_id.get(paragraph_id)
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
                    "layout_region": layout_region.region if layout_region is not None else "unknown",
                    "layout_column": layout_region.column_id if layout_region is not None else None,
                    "layout_confidence": layout_region.confidence if layout_region is not None else 0.0,
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
            "layout_summaries": self._layout_summaries_payload(),
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
        glyph_samples: list[dict[str, Any]] = []
        glyph_normalized = 0
        self._symbol_font_ids_by_paragraph_object_id = {}
        self._detached_i2c_visual_record_ids = set()
        for page_index, page in enumerate(pages):
            page_number = _page_number(page, page_index)
            page_rect = _page_rect(page)
            symbol_font_ids_by_xobj = _symbol_font_ids_by_xobj(page)
            paragraphs = getattr(page, "pdf_paragraph", []) or []
            for paragraph_index, paragraph in enumerate(paragraphs):
                xobj_id = getattr(paragraph, "xobj_id", None)
                symbol_font_ids = symbol_font_ids_by_xobj.get(xobj_id) or symbol_font_ids_by_xobj.get(None) or frozenset()
                if symbol_font_ids:
                    self._symbol_font_ids_by_paragraph_object_id[id(paragraph)] = symbol_font_ids
                text = str(getattr(paragraph, "unicode", "") or "")
                layout_label = getattr(paragraph, "layout_label", None)
                if (
                    layout_label in {"fallback_line", "figure_caption"}
                    and self.hook_policy.is_apply("normalize_symbol_glyph_fallback_line_text")
                ):
                    rebuilt = _rebuild_fallback_line_text(paragraph, symbol_font_ids=symbol_font_ids)
                    if rebuilt and rebuilt != text:
                        paragraph.unicode = rebuilt
                        if len(glyph_samples) < 8:
                            glyph_samples.append(
                                {
                                    "page_number": page_number,
                                    "paragraph_index": paragraph_index + 1,
                                    "layout_label": layout_label,
                                    "incoming_text": text[:120],
                                    "outgoing_text": rebuilt[:120],
                                }
                            )
                        glyph_normalized += 1
                        text = rebuilt
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
        if self.hook_policy.is_apply("protect_detached_i2c_fallback_line_text"):
            detached_samples = _detect_detached_i2c_fallback_line_records(records, self.paragraphs_by_id)
            if detached_samples:
                self._detached_i2c_visual_record_ids.update(sample["paragraph_id"] for sample in detached_samples)
                self._record_action(
                    "protect_detached_i2c_fallback_line_text",
                    rule_key="protect_detached_i2c_fallback_line_text",
                    decision="applied",
                    paragraphs=len(detached_samples),
                    samples=detached_samples[:8],
                )
        if glyph_normalized:
            self._record_action(
                "normalize_symbol_glyph_fallback_line_text",
                rule_key="normalize_symbol_glyph_fallback_line_text",
                decision="applied",
                paragraphs=glyph_normalized,
                samples=glyph_samples,
            )
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

    def _build_page_layout_summaries(self, records: list[_ParagraphRecord]) -> None:
        self.layout_regions_by_id = {}
        self.page_layout_summaries = {}
        by_page: dict[int, list[_ParagraphRecord]] = {}
        for record in records:
            by_page.setdefault(record.page_number, []).append(record)
        for page_number, page_records in by_page.items():
            summary, regions = _build_page_layout_summary(page_number, page_records)
            self.page_layout_summaries[page_number] = summary
            self.layout_regions_by_id.update({region.paragraph_id: region for region in regions})

    def _layout_region_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for region in self.layout_regions_by_id.values():
            key = region.region if region.column_id is None else f"{region.region}:{region.column_id}"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _layout_summaries_payload(self) -> list[dict[str, Any]]:
        payload = []
        for page_number in sorted(self.page_layout_summaries):
            summary = self.page_layout_summaries[page_number]
            payload.append(
                {
                    "page_number": summary.page_number,
                    "columns": [
                        {"column_id": column_id, "x1": round(x1, 3), "x2": round(x2, 3)}
                        for column_id, x1, x2 in summary.columns
                    ],
                    "counts": summary.counts,
                }
            )
        return payload

    def _record_layout_region(self, record: _ParagraphRecord | None) -> _LayoutRegion | None:
        if record is None:
            return None
        return self.layout_regions_by_id.get(record.paragraph_id)

    def _guard_merge_records(
        self,
        left_record: _ParagraphRecord | None,
        right_record: _ParagraphRecord | None,
    ) -> dict[str, Any]:
        if left_record is None or right_record is None:
            return {"guard_decision": "rejected", "guard_reason": "missing_record"}
        left_region = self._record_layout_region(left_record)
        right_region = self._record_layout_region(right_record)
        payload = _layout_guard_payload("left", left_region) | _layout_guard_payload("right", right_region)
        if left_record.page_number != right_record.page_number:
            return payload | {"guard_decision": "rejected", "guard_reason": "cross_page"}
        if left_region is None or right_region is None:
            return payload | {"guard_decision": "rejected", "guard_reason": "missing_layout_region"}
        if left_region.region == "unknown" or right_region.region == "unknown":
            return payload | {"guard_decision": "rejected", "guard_reason": "unknown_region"}
        if left_region.region != "body_column" or right_region.region != "body_column":
            return payload | {"guard_decision": "rejected", "guard_reason": "non_body_region"}
        if left_region.column_id != right_region.column_id:
            return payload | {"guard_decision": "rejected", "guard_reason": "cross_column"}
        return payload | {"guard_decision": "allowed", "guard_reason": "same_body_column"}

    def _guard_split_record(self, record: _ParagraphRecord | None, reason: str) -> dict[str, Any]:
        region = self._record_layout_region(record)
        payload = _layout_guard_payload("target", region)
        if record is None:
            return payload | {"guard_decision": "rejected", "guard_reason": "missing_record"}
        if reason == "multiline_body_block":
            return payload | {"guard_decision": "rejected", "guard_reason": "multiline_body_block"}
        if reason == "fallback_line_visual_split" and _is_compact_technical_label_record(record):
            return payload | {"guard_decision": "allowed", "guard_reason": "fallback_line_technical_label"}
        if region is None or region.region == "unknown":
            return payload | {"guard_decision": "rejected", "guard_reason": "unknown_region"}
        if reason == "inline_numbered_markers" and region.region == "body_column":
            return payload | {"guard_decision": "allowed", "guard_reason": "numbered_marker_same_region"}
        return payload | {"guard_decision": "rejected", "guard_reason": "ordinary_body_split"}

    def _guard_remove_records(
        self,
        candidate_record: _ParagraphRecord | None,
        anchor_record: _ParagraphRecord | None,
    ) -> dict[str, Any]:
        guard = self._guard_merge_records(anchor_record, candidate_record)
        if guard.get("guard_decision") == "allowed":
            guard["guard_reason"] = "same_body_column_duplicate"
        return guard

    def _guard_collapse_records(
        self,
        base_record: _ParagraphRecord | None,
        absorbed_records: list[_ParagraphRecord | None],
    ) -> dict[str, Any]:
        if base_record is None:
            return {"guard_decision": "rejected", "guard_reason": "missing_base_record"}
        rejected_guard: dict[str, Any] | None = None
        for absorbed_record in absorbed_records:
            guard = self._guard_remove_records(absorbed_record, base_record)
            if guard.get("guard_decision") == "rejected":
                rejected_guard = guard
                break
        base_region = self._record_layout_region(base_record)
        if rejected_guard is not None:
            if self._looks_like_safe_overlap_collapse_cluster(base_record, absorbed_records):
                return _layout_guard_payload("base", base_region) | {
                    "guard_decision": "allowed",
                    "guard_reason": "safe_overlap_fragment_cluster",
                }
            return rejected_guard
        return _layout_guard_payload("base", base_region) | {
            "guard_decision": "allowed",
            "guard_reason": "same_body_column_overlap",
        }

    def _looks_like_safe_overlap_collapse_cluster(
        self,
        base_record: _ParagraphRecord,
        absorbed_records: list[_ParagraphRecord | None],
    ) -> bool:
        records = [base_record, *[record for record in absorbed_records if record is not None]]
        if len(records) < 3 or len(records) != len(absorbed_records) + 1:
            return False
        if any(record.page_number != base_record.page_number for record in records):
            return False
        if any(record.xobj_id != base_record.xobj_id for record in records):
            return False
        for record in records:
            if record.role in {"toc_entry", "vertical_label", "running_edge_text"} or record.rect is None:
                return False
            region = self._record_layout_region(record)
            if region is not None and region.region not in {"body_column", "table", "unknown"}:
                return False
        return _records_look_like_overlapping_fragment_cluster(records)

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


def _build_page_layout_summary(
    page_number: int,
    records: list[_ParagraphRecord],
) -> tuple[_PageLayoutSummary, list[_LayoutRegion]]:
    columns = _detect_body_columns(records)
    regions = [_classify_layout_region(record, columns) for record in records]
    counts: dict[str, int] = {}
    for region in regions:
        key = region.region if region.column_id is None else f"{region.region}:{region.column_id}"
        counts[key] = counts.get(key, 0) + 1
    return _PageLayoutSummary(page_number=page_number, columns=tuple(columns), counts=counts), regions


def _detect_body_columns(records: list[_ParagraphRecord]) -> list[tuple[str, float, float]]:
    candidates = [
        record
        for record in records
        if record.rect is not None
        and record.page_rect is not None
        and record.role == "body"
        and record.policy == "pass_through"
        and not record.vertical
        and not _is_edge_band(record)
        and not _looks_like_layout_table_record(record)
    ]
    if len(candidates) < _LAYOUT_MIN_COLUMN_CANDIDATES:
        return []

    page_rect = candidates[0].page_rect
    if page_rect is None:
        return []
    page_width = max(page_rect[2] - page_rect[0], 1.0)
    centers = [
        ((record.rect[0] + record.rect[2]) / 2.0, record)
        for record in candidates
        if record.rect is not None
    ]
    centers.sort(key=lambda item: item[0])
    if len(centers) >= _LAYOUT_MIN_TWO_COLUMN_CANDIDATES:
        gaps = [
            (centers[index + 1][0] - centers[index][0], index)
            for index in range(len(centers) - 1)
        ]
        largest_gap, split_index = max(gaps, key=lambda item: item[0])
        left_records = [record for _center, record in centers[: split_index + 1]]
        right_records = [record for _center, record in centers[split_index + 1 :]]
        min_gap = max(
            _LAYOUT_TWO_COLUMN_MIN_GAP_POINTS,
            page_width * _LAYOUT_TWO_COLUMN_MIN_GAP_PAGE_RATIO,
        )
        if (
            largest_gap >= min_gap
            and len(left_records) >= _LAYOUT_MIN_RECORDS_PER_COLUMN
            and len(right_records) >= _LAYOUT_MIN_RECORDS_PER_COLUMN
        ):
            return [
                ("left", _records_min_x(left_records), _records_max_x(left_records)),
                ("right", _records_min_x(right_records), _records_max_x(right_records)),
            ]
    return [("single", _records_min_x(candidates), _records_max_x(candidates))]


def _classify_layout_region(
    record: _ParagraphRecord,
    columns: list[tuple[str, float, float]],
) -> _LayoutRegion:
    if record.role == "running_edge_text" or _is_edge_band(record):
        return _LayoutRegion(record.paragraph_id, record.page_number, "edge", None, _LAYOUT_EDGE_CONFIDENCE, "edge_band")
    if record.role == "vertical_label":
        return _LayoutRegion(record.paragraph_id, record.page_number, "edge", None, _LAYOUT_VERTICAL_LABEL_CONFIDENCE, "vertical_label")
    if _looks_like_layout_table_record(record):
        return _LayoutRegion(record.paragraph_id, record.page_number, "table", None, _LAYOUT_TABLE_CONFIDENCE, "layout_label_table")
    if _looks_like_layout_figure_record(record):
        return _LayoutRegion(record.paragraph_id, record.page_number, "figure", None, _LAYOUT_FIGURE_CONFIDENCE, "layout_label_figure")
    if record.role != "body" or record.policy != "pass_through" or record.rect is None:
        return _LayoutRegion(record.paragraph_id, record.page_number, "unknown", None, 0.0, "non_body_or_missing_rect")
    center_x = (record.rect[0] + record.rect[2]) / 2.0
    for column_id, x1, x2 in columns:
        tolerance = max(_LAYOUT_COLUMN_TOLERANCE_POINTS, (x2 - x1) * _LAYOUT_COLUMN_TOLERANCE_RATIO)
        if x1 - tolerance <= center_x <= x2 + tolerance:
            confidence = (
                _LAYOUT_TWO_COLUMN_BODY_CONFIDENCE
                if column_id in {"left", "right"}
                else _LAYOUT_SINGLE_COLUMN_BODY_CONFIDENCE
            )
            return _LayoutRegion(record.paragraph_id, record.page_number, "body_column", column_id, confidence, "x_distribution")
    return _LayoutRegion(record.paragraph_id, record.page_number, "unknown", None, 0.0, "outside_detected_columns")


def _layout_guard_payload(prefix: str, region: _LayoutRegion | None) -> dict[str, Any]:
    if region is None:
        return {f"{prefix}_region": "unknown", f"{prefix}_column": None, f"{prefix}_layout_confidence": 0.0}
    return {
        f"{prefix}_region": region.region,
        f"{prefix}_column": region.column_id,
        f"{prefix}_layout_confidence": round(region.confidence, 3),
    }


def _looks_like_layout_table_record(record: _ParagraphRecord) -> bool:
    label = str(record.layout_label or "").casefold()
    return "table" in label


def _looks_like_layout_figure_record(record: _ParagraphRecord) -> bool:
    label = str(record.layout_label or "").casefold()
    return any(token in label for token in ("figure", "image", "caption"))


def _records_min_x(records: list[_ParagraphRecord]) -> float:
    return min(record.rect[0] for record in records if record.rect is not None)


def _records_max_x(records: list[_ParagraphRecord]) -> float:
    return max(record.rect[2] for record in records if record.rect is not None)


def _same_line_merge_sample(left: Any, right: Any) -> dict[str, Any]:
    return {
        "left": str(getattr(left, "unicode", "") or "")[:80],
        "right": str(getattr(right, "unicode", "") or "")[:80],
        "rect": _box_rect(getattr(left, "box", None)),
    }


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


def _is_edge_metadata_preserve_candidate(record: _ParagraphRecord) -> bool:
    if not _is_edge_band(record):
        return False
    text = unicodedata.normalize("NFKC", record.text).strip()
    if not text or len(text) > 96:
        return False
    if re.search(r"\b(?:SBAS|SBAA|SLOS|SLAS|SLVS|SNAS|SLLS|SLUS|SLES)[A-Z0-9]{3,}\b", text, re.IGNORECASE):
        return True
    if re.search(
        r"\b(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{4}\b",
        text,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"\b(?:REVISED|REV\.?|COPYRIGHT|www\.)\b|©", text, re.IGNORECASE):
        return True
    if re.fullmatch(r"\d{1,4}", text):
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
    if _looks_like_translatable_fallback_line_text(text):
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
    if record.xobj_id not in {None, 0} and any(char.isupper() for char in compact) and not re.search(r"[a-z]", text):
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


def _looks_like_inline_broken_word_continuation(
    left_text: str,
    right_text: str,
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    left = unicodedata.normalize("NFKC", left_text).strip()
    right = unicodedata.normalize("NFKC", right_text).strip()
    if not left or not right:
        return False
    if _PAGE_NUMBER_RE.fullmatch(right):
        return False
    if not left[-1].isalpha() or not right[0].islower():
        return False
    if _SHORT_UPPER_TOKEN_RE.fullmatch(right) and not left[-1].islower():
        return False
    gap = right_rect[0] - left_rect[2]
    height = max(min(left_rect[3] - left_rect[1], right_rect[3] - right_rect[1]), 1.0)
    if not (-0.5 <= gap <= max(2.0, height * 0.25)):
        return False
    compact_right = re.sub(r"[^A-Za-z]", "", right)
    if not re.match(r"^[a-z]{1,12}(?:\b|[A-Z])", compact_right):
        return False
    return bool(re.search(r"[a-z]", compact_right))


def _is_tight_inline_join(
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    gap = right_rect[0] - left_rect[2]
    height = max(min(left_rect[3] - left_rect[1], right_rect[3] - right_rect[1]), 1.0)
    return -0.5 <= gap <= max(1.2, height * 0.12)


def _looks_like_inline_micro_fragment_continuation(left: Any, right: Any) -> bool:
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or right_rect is None:
        return False
    baseline_ok, _reason = _same_baseline_close_gap(left_rect, right_rect)
    if not baseline_ok:
        return False
    gap = right_rect[0] - left_rect[2]
    height = max(min(left_rect[3] - left_rect[1], right_rect[3] - right_rect[1]), 1.0)
    if not (-0.75 <= gap <= max(3.0, height * 0.42)):
        return False
    left_text = unicodedata.normalize("NFKC", str(getattr(left, "unicode", "") or "")).strip()
    right_text = unicodedata.normalize("NFKC", str(getattr(right, "unicode", "") or "")).strip()
    if not left_text or not right_text:
        return False
    if _PAGE_NUMBER_RE.fullmatch(left_text) or _PAGE_NUMBER_RE.fullmatch(right_text):
        return False
    if not (_is_inline_micro_text_fragment(left_text) or _is_inline_micro_text_fragment(right_text)):
        return False
    combined = f"{left_text}{right_text}"
    return _looks_like_prose_fragment(combined)


def _looks_like_same_line_text_continuation(left: Any, right: Any) -> bool:
    left_text = unicodedata.normalize("NFKC", str(getattr(left, "unicode", "") or "")).strip()
    right_text = unicodedata.normalize("NFKC", str(getattr(right, "unicode", "") or "")).strip()
    if not _looks_like_mergeable_line_fragment(left_text, right_text):
        return False
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or right_rect is None:
        return False
    baseline_ok, _reason = _same_baseline_close_gap(left_rect, right_rect)
    if not baseline_ok:
        return False
    return _looks_like_broken_word_boundary(left_text, right_text) or (
        not _ends_sentence_like(left_text) and _looks_like_lowercase_continuation(right_text)
    )


def _is_inline_micro_text_fragment(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    compact = _SPACE_COLLAPSE_RE.sub("", normalized)
    if not compact or len(compact) > 18:
        return False
    if any(char.isalpha() for char in compact):
        return True
    return bool(re.fullmatch(r"[.。,:;!?-]+", compact))


def _looks_like_inline_decimal_continuation(left: Any, right: Any) -> bool:
    left_text = unicodedata.normalize("NFKC", str(getattr(left, "unicode", "") or "")).strip()
    right_text = unicodedata.normalize("NFKC", str(getattr(right, "unicode", "") or "")).strip()
    if re.search(r"[-+±]?\d+\.$", left_text) is None:
        return False
    if re.match(r"^\d+(?:[A-Za-z%°ΩΩµμ]|$)", right_text) is None:
        return False
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or right_rect is None:
        return False
    baseline_ok, _reason = _same_baseline_close_gap(left_rect, right_rect)
    return baseline_ok


def _looks_like_prose_fragment(text: str) -> bool:
    letters = sum(1 for char in text if char.isalpha())
    if letters < 3:
        return False
    return bool(re.search(r"[a-z]", text)) or bool(re.search(r"\s", text))


def _looks_like_contiguous_body_line_pair(
    left_text: str,
    right_text: str,
    left_rect: tuple[float, float, float, float],
    right_rect: tuple[float, float, float, float],
) -> bool:
    left = unicodedata.normalize("NFKC", str(left_text or "")).strip()
    right = unicodedata.normalize("NFKC", str(right_text or "")).strip()
    if not left or not right:
        return False
    if not _looks_like_prose_fragment(left) or not _looks_like_prose_fragment(right):
        return False
    if _ends_sentence_like(left):
        return False
    if not (_looks_like_broken_word_boundary(left, right) or _looks_like_lowercase_continuation(right)):
        return False
    left_height = max(left_rect[3] - left_rect[1], 1.0)
    right_height = max(right_rect[3] - right_rect[1], 1.0)
    vertical_gap = left_rect[1] - right_rect[3]
    if not (-2.0 <= vertical_gap <= max(6.0, min(left_height, right_height) * 0.72)):
        return False
    left_width = left_rect[2] - left_rect[0]
    right_width = right_rect[2] - right_rect[0]
    if min(left_width, right_width) < 48.0:
        return False
    x_delta = abs(left_rect[0] - right_rect[0])
    if x_delta > max(8.0, min(left_width, right_width) * 0.08):
        return False
    return True


def _ends_sentence_like(text: str) -> bool:
    stripped = unicodedata.normalize("NFKC", str(text or "")).rstrip()
    if not stripped:
        return False
    return bool(re.search(r"[.!?。！？:：;；]\s*(?:[])}）】\"'”’]*)$", stripped))


def _looks_like_lowercase_continuation(text: str) -> bool:
    stripped = unicodedata.normalize("NFKC", str(text or "")).lstrip()
    if not stripped:
        return False
    first = stripped[0]
    if first.islower() or first.isdigit() or first in "([{（":
        return True
    return bool(re.match(r"(?:and|or|of|to|for|with|in|on|by|from|unless|that|which|as|so)\b", stripped, re.IGNORECASE))


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


def _looks_like_multiline_prose_block(
    paragraph: Any,
    rect: tuple[float, float, float, float],
    text: str,
) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if len(normalized) < 40 or not _looks_like_prose_fragment(normalized):
        return False
    style = getattr(paragraph, "pdf_style", None)
    font_size = float(getattr(style, "font_size", 0) or 0) or 10.0
    height = max(rect[3] - rect[1], 1.0)
    return height / font_size >= 2.6


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


def _records_look_like_overlapping_fragment_cluster(records: list[_ParagraphRecord]) -> bool:
    if len(records) < 3:
        return False
    entries = [(record, record.rect, unicodedata.normalize("NFKC", record.text).strip()) for record in records]
    if any(rect is None or not text for _record, rect, text in entries):
        return False
    anchor_record, anchor_rect, anchor_text = max(
        entries,
        key=lambda item: (len(_SPACE_COLLAPSE_RE.sub("", item[2])), item[1][2] - item[1][0]),
    )
    if len(_SPACE_COLLAPSE_RE.sub("", anchor_text)) < 24:
        return False
    overlapping = 0
    short_fragments = 0
    for record, rect, text in entries:
        if record.paragraph_id == anchor_record.paragraph_id:
            continue
        if not _same_overlap_fragment_baseline(anchor_rect, rect):
            return False
        if _horizontal_overlap_width(anchor_rect, rect) <= 0 and rect[0] > anchor_rect[2] + 6.0:
            return False
        overlapping += 1
        if len(_SPACE_COLLAPSE_RE.sub("", text)) <= 8:
            short_fragments += 1
    return overlapping >= 2 and short_fragments >= 2


def _build_overlap_collapse_cluster(
    paragraphs: list[Any],
    group: list[int],
    removed_indices: set[int],
) -> _OverlapCollapseCluster | None:
    live_group = [(index, paragraphs[index]) for index in group if index not in removed_indices]
    if not _looks_like_overlapping_fragment_cluster(live_group):
        return None
    ordered_group = tuple(
        sorted(
            live_group,
            key=lambda item: (
                _box_rect(getattr(item[1], "box", None))
                or (math.inf, math.inf, math.inf, math.inf)
            )[0],
        )
    )
    base_index, base = _overlapping_fragment_anchor(list(ordered_group))
    merged_text = ""
    merged_rect: tuple[float, float, float, float] | None = None
    absorbed_indices: list[int] = []
    for candidate_index, candidate in ordered_group:
        candidate_rect = _box_rect(getattr(candidate, "box", None))
        if candidate_rect is None:
            continue
        if merged_rect is None:
            merged_text = str(getattr(candidate, "unicode", "") or "")
            merged_rect = candidate_rect
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
        absorbed_indices.append(candidate_index)
    if len(absorbed_indices) < 3 or merged_rect is None:
        return None
    return _OverlapCollapseCluster(
        ordered_group=ordered_group,
        base_index=base_index,
        base=base,
        absorbed_indices=tuple(absorbed_indices),
        merged_text=merged_text,
        merged_rect=merged_rect,
    )


def _overlapping_fragment_anchor(group: list[tuple[int, Any]]) -> tuple[int, Any]:
    return max(
        group,
        key=lambda item: (
            len(_SPACE_COLLAPSE_RE.sub("", str(getattr(item[1], "unicode", "") or ""))),
            ((_box_rect(getattr(item[1], "box", None)) or (0.0, 0.0, 0.0, 0.0))[2] - (_box_rect(getattr(item[1], "box", None)) or (0.0, 0.0, 0.0, 0.0))[0]),
        ),
    )


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


def _best_wrapped_same_line_tail_left_neighbor(
    right: Any,
    first_group_rect: tuple[float, float, float, float],
    first_group_text: str,
    ordered_items: list[tuple[Any, int]],
    hook_context: BabeldocHookContext,
) -> Any | None:
    best: tuple[tuple[float, float], Any] | None = None
    for left, _left_original_index in ordered_items:
        if left is right:
            continue
        if getattr(left, "xobj_id", None) != getattr(right, "xobj_id", None):
            continue
        left_record = hook_context._record_for_paragraph(left)
        right_record = hook_context._record_for_paragraph(right)
        if left_record is None or right_record is None:
            continue
        if left_record.role != "body" or right_record.role != "body":
            continue
        guard = hook_context._guard_merge_records(left_record, right_record)
        if guard.get("guard_decision") == "rejected":
            continue
        left_rect = _box_rect(getattr(left, "box", None))
        if left_rect is None:
            continue
        if not _same_visual_line(left_rect, first_group_rect):
            continue
        if left_rect[2] > first_group_rect[0] + 1.0:
            continue
        gap = first_group_rect[0] - left_rect[2]
        height = max(min(left_rect[3] - left_rect[1], first_group_rect[3] - first_group_rect[1]), 1.0)
        if gap > max(8.0, height * 0.85):
            continue
        left_text = str(getattr(left, "unicode", "") or "")
        if not _looks_like_mergeable_line_fragment(left_text, first_group_text):
            continue
        score = (gap, -left_rect[2])
        if best is None or score < best[0]:
            best = (score, left)
    return None if best is None else best[1]


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
            for char in self.chars:
                font_size = max(char.pdf_style.font_size * final_scale, 0.1)
                positioned_chars.append((char, font_size, baseline_offset))
                baseline_offset += _vertical_axis_label_advance(char, font_size)
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
    corrected_unit = f"μ{match.group('unit')[1:]}"
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


def _symbol_font_ids_by_xobj(page: Any) -> dict[int | str | None, frozenset[str]]:
    page_symbol_ids = _symbol_font_ids(getattr(page, "pdf_font", []) or [])
    by_xobj: dict[int | str | None, frozenset[str]] = {None: page_symbol_ids}
    for xobj in getattr(page, "pdf_xobject", []) or []:
        xobj_id = getattr(xobj, "xobj_id", None)
        if xobj_id is None:
            continue
        by_xobj[xobj_id] = page_symbol_ids | _symbol_font_ids(getattr(xobj, "pdf_font", []) or [])
    return by_xobj


def _symbol_font_ids(fonts: list[Any]) -> frozenset[str]:
    ids: set[str] = set()
    for font in fonts:
        font_id = getattr(font, "font_id", None)
        if font_id is None:
            continue
        font_name = str(getattr(font, "name", "") or font_id)
        if _is_symbol_font_name(font_name):
            ids.add(str(font_id))
    return frozenset(ids)


def _is_symbol_font_name(font_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(font_name or "").lower())
    return "symbol" in normalized


def _detect_detached_i2c_fallback_line_records(
    records: list[_ParagraphRecord],
    paragraphs_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    by_group: dict[tuple[int, int | str | None], list[_ParagraphRecord]] = {}
    for record in records:
        if record.layout_label != "fallback_line" or record.rect is None:
            continue
        by_group.setdefault((record.page_number, record.xobj_id), []).append(record)

    samples: list[dict[str, Any]] = []
    for group_records in by_group.values():
        superscripts = [record for record in group_records if _is_detached_i2c_superscript_record(record)]
        if not superscripts:
            continue
        for record in group_records:
            paragraph = paragraphs_by_id.get(record.paragraph_id)
            if paragraph is None or not _looks_like_detached_i2c_host_text(record.text):
                continue
            matched_superscript = _matching_detached_i2c_superscript(paragraph, record, superscripts)
            if matched_superscript is None:
                continue
            samples.append(
                {
                    "paragraph_id": record.paragraph_id,
                    "superscript_id": matched_superscript.paragraph_id,
                    "page_number": record.page_number,
                    "text": record.text[:120],
                    "semantic_text": _detached_i2c_semantic_text(record.text)[:120],
                    "rect": record.rect,
                    "superscript_rect": matched_superscript.rect,
                }
            )
    return samples


def _looks_like_detached_i2c_host_text(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    return bool(re.search(r"(?<![A-Za-z])I\s+C(?=\s+[A-Za-z][A-Za-z -]{2,40}\b)", normalized))


def _detached_i2c_semantic_text(text: str) -> str:
    return re.sub(r"(?<![A-Za-z])I\s+C(?=\s+[A-Za-z][A-Za-z -]{2,40}\b)", "I2C", str(text or ""))


def _detached_i2c_visual_text(text: str) -> str:
    return re.sub(r"(?<![A-Za-z])I2C(?=\s+\S)", "I C", str(text or ""))


def _is_detached_i2c_superscript_record(record: _ParagraphRecord) -> bool:
    if record.rect is None:
        return False
    text = unicodedata.normalize("NFKC", record.text).strip()
    if text != "2":
        return False
    width = record.rect[2] - record.rect[0]
    height = record.rect[3] - record.rect[1]
    return width <= 4.2 and height <= 4.8


def _matching_detached_i2c_superscript(
    host_paragraph: Any,
    host_record: _ParagraphRecord,
    superscripts: list[_ParagraphRecord],
) -> _ParagraphRecord | None:
    i_char, c_char = _detached_i2c_host_boundary_chars(_collect_fallback_line_chars(host_paragraph))
    if i_char is None or c_char is None:
        return None
    i_rect = _box_rect(getattr(i_char, "box", None))
    c_rect = _box_rect(getattr(c_char, "box", None))
    if i_rect is None or c_rect is None:
        return None
    base_height = max(i_rect[3] - i_rect[1], c_rect[3] - c_rect[1], 1.0)
    i_center = (i_rect[0] + i_rect[2]) / 2
    c_center = (c_rect[0] + c_rect[2]) / 2
    top = min(i_rect[1], c_rect[1])
    bottom = max(i_rect[3], c_rect[3])
    best: tuple[float, _ParagraphRecord] | None = None
    for superscript in superscripts:
        if superscript.paragraph_id == host_record.paragraph_id or superscript.rect is None:
            continue
        rect = superscript.rect
        center_x = (rect[0] + rect[2]) / 2
        center_y = (rect[1] + rect[3]) / 2
        if not i_center <= center_x <= c_center + base_height * 0.45:
            continue
        if not top - base_height * 0.9 <= center_y <= bottom + base_height * 0.9:
            continue
        score = abs(center_x - ((i_center + c_center) / 2)) + abs(center_y - top)
        if best is None or score < best[0]:
            best = (score, superscript)
    return best[1] if best is not None else None


def _detached_i2c_host_boundary_chars(chars: list[Any]) -> tuple[Any | None, Any | None]:
    non_space = [char for char in chars if str(getattr(char, "char_unicode", "") or "").strip()]
    for index, char in enumerate(non_space[:-1]):
        if str(getattr(char, "char_unicode", "") or "") != "I":
            continue
        next_char = non_space[index + 1]
        if str(getattr(next_char, "char_unicode", "") or "") == "C":
            return char, next_char
    return None, None


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
                    "rect": _rect_union([_box_rect(getattr(char, "box", None)) for char in formula_chars]),
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


def _page_level_axis_tick_groups(
    chars: list[Any],
    records: Any,
    page_number: int | None,
) -> list[list[Any]]:
    if page_number is None:
        return []
    page_records = [
        record
        for record in records
        if record.page_number == page_number and record.rect is not None and record.xobj_id is not None
    ]
    if not page_records:
        return []
    groups: list[list[Any]] = []
    grouped_keys: set[tuple[int | str | None, int, ...]] = set()
    for label_record in page_records:
        if not _looks_like_horizontal_axis_label(label_record.text):
            continue
        label_rect = label_record.rect
        if label_rect is None:
            continue
        candidates = _axis_tick_candidate_chars(chars, label_record)
        columns = _axis_tick_columns(candidates)
        valid_columns = [column for column in columns if _is_axis_tick_column(column, label_rect)]
        if len(valid_columns) < 4:
            continue
        for column in valid_columns:
            key = (label_record.xobj_id, *sorted(id(char) for char in column))
            if key in grouped_keys:
                continue
            grouped_keys.add(key)
            groups.append(column)
    return groups


def _axis_tick_candidate_chars(chars: list[Any], label_record: _ParagraphRecord) -> list[Any]:
    label_rect = label_record.rect
    if label_rect is None:
        return []
    x1, _y1, x2, y2 = label_rect
    horizontal_padding = max(x2 - x1, 80.0)
    candidates = []
    for char in chars:
        if getattr(char, "xobj_id", None) != label_record.xobj_id:
            continue
        text = unicodedata.normalize("NFKC", str(getattr(char, "char_unicode", "") or "")).strip()
        if not _is_axis_tick_char_text(text):
            continue
        rect = _box_rect(getattr(char, "box", None))
        if rect is None:
            continue
        if rect[1] < y2 - 1.0 or rect[3] > y2 + 36.0:
            continue
        if rect[0] < x1 - horizontal_padding or rect[2] > x2 + horizontal_padding:
            continue
        if not _is_compact_axis_tick_char(char, rect):
            continue
        candidates.append(char)
    return candidates


def _is_axis_tick_char_text(text: str) -> bool:
    if len(text) != 1:
        return False
    return text.isdigit() or text in {".", "+", "-", "−"}


def _is_compact_axis_tick_char(char: Any, rect: tuple[float, float, float, float]) -> bool:
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    if width <= 0 or height <= 0 or width > 10.0 or height > 8.0:
        return False
    font_size = float(getattr(getattr(char, "pdf_style", None), "font_size", 0) or 0)
    return 0 < font_size <= 5.5


def _axis_tick_columns(chars: list[Any]) -> list[list[Any]]:
    columns: list[list[tuple[float, Any]]] = []
    for char in sorted(chars, key=lambda item: (_char_center_x(item), _char_center_y(item))):
        center_x = _char_center_x(char)
        matched: list[tuple[float, Any]] | None = None
        for column in columns:
            column_x = sum(item[0] for item in column) / len(column)
            if abs(center_x - column_x) <= 3.0:
                matched = column
                break
        if matched is None:
            columns.append([(center_x, char)])
        else:
            matched.append((center_x, char))
    return [[char for _center_x, char in column] for column in columns]


def _is_axis_tick_column(group: list[Any], label_rect: tuple[float, float, float, float]) -> bool:
    if not 4 <= len(group) <= 7:
        return False
    rect = _char_group_rect(group)
    if rect is None:
        return False
    width = rect[2] - rect[0]
    height = rect[3] - rect[1]
    if height < 10.0 or height < width * 1.8:
        return False
    if rect[1] < label_rect[3] - 1.0 or rect[3] > label_rect[3] + 36.0:
        return False
    text = unicodedata.normalize("NFKC", _char_group_text(group)).replace("−", "-")
    text = _SPACE_COLLAPSE_RE.sub("", text)
    return bool(re.fullmatch(r"[+-]?(?:\d\.\d{2,4}|\d{4,5})", text))


def _char_center_x(char: Any) -> float:
    rect = _box_rect(getattr(char, "box", None))
    if rect is None:
        return math.inf
    return (rect[0] + rect[2]) / 2


def _char_center_y(char: Any) -> float:
    rect = _box_rect(getattr(char, "box", None))
    if rect is None:
        return math.inf
    return (rect[1] + rect[3]) / 2


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


def _is_page_edge_rect(
    rect: tuple[float, float, float, float],
    records: list[_ParagraphRecord],
) -> bool:
    page_rect = next((record.page_rect for record in records if record.page_rect is not None), None)
    if page_rect is None:
        return False
    x1, y1, x2, y2 = rect
    px1, py1, px2, py2 = page_rect
    width = max(px2 - px1, 1.0)
    height = max(py2 - py1, 1.0)
    return (
        y1 <= py1 + height * 0.1
        or y2 >= py2 - height * 0.1
        or x1 <= px1 + width * 0.06
        or x2 >= px2 - width * 0.06
    )


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
    placeholder_spans = [
        match.span()
        for pattern in (_PLACEHOLDER_TOKEN_RE, _BABELDOC_STYLE_PLACEHOLDER_RE)
        for match in pattern.finditer(text)
    ]
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
            if _span_inside_any(start, end, placeholder_spans):
                continue
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


def _span_inside_any(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(span_start <= start and end <= span_end for span_start, span_end in spans)


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
                "rule_key": "formula_placeholder_translation_input_override",
                "rule_kind": "text_only",
                "decision": "applied",
                "paragraph_id": record.paragraph_id,
                "role": record.role,
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
            "rule_key": "composition_translation_input_override",
            "rule_kind": "text_only",
            "decision": "applied",
            "paragraph_id": record.paragraph_id,
            "role": record.role,
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


def _body_paragraph_reference_font_size(paragraph: Any) -> float:
    runs = []
    for item in getattr(paragraph, "pdf_paragraph_composition", []) or []:
        same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
        if same_style_unicode is None:
            continue
        text = _strip_babeldoc_style_placeholders(str(getattr(same_style_unicode, "unicode", "") or "")).strip()
        if not text or _is_size_sensitive_inline_marker(text):
            continue
        style = getattr(same_style_unicode, "pdf_style", None)
        size = float(getattr(style, "font_size", 0) or 0)
        if size <= 0:
            continue
        runs.append((size, max(_display_width(text), 1)))
    if runs:
        return _weighted_median_size(runs)

    base_style = getattr(paragraph, "pdf_style", None)
    return float(getattr(base_style, "font_size", 0) or 0)


def _body_scale_lane_id(paragraph: Any, lanes: list[dict[str, Any]]) -> int:
    for lane_id, lane in enumerate(lanes):
        if _same_body_scale_lane(lane["rect"], paragraph):
            rect = _box_rect(getattr(paragraph, "box", None))
            if rect is not None:
                lane["rect"] = _rect_union([lane["rect"], rect]) or lane["rect"]
            return lane_id
    lane_id = len(lanes)
    rect = _box_rect(getattr(paragraph, "box", None))
    lanes.append({"rect": rect})
    return lane_id


def _same_body_scale_lane(left_rect: tuple[float, float, float, float] | None, right: Any) -> bool:
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or right_rect is None:
        return False
    min_width = max(min(left_rect[2] - left_rect[0], right_rect[2] - right_rect[0]), 1.0)
    if abs(left_rect[0] - right_rect[0]) <= max(10.0, min_width * 0.12):
        return True
    if abs(left_rect[2] - right_rect[2]) <= max(12.0, min_width * 0.12):
        return True
    left_center = (left_rect[0] + left_rect[2]) / 2.0
    right_center = (right_rect[0] + right_rect[2]) / 2.0
    width_delta = abs((left_rect[2] - left_rect[0]) - (right_rect[2] - right_rect[0]))
    return width_delta <= max(18.0, min_width * 0.25) and abs(left_center - right_center) <= max(18.0, min_width * 0.16)


def _apply_body_target_font_size(paragraph: Any, target_size: float) -> int:
    changed = 0
    for item in getattr(paragraph, "pdf_paragraph_composition", []) or []:
        same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
        if same_style_unicode is not None:
            text = _strip_babeldoc_style_placeholders(str(getattr(same_style_unicode, "unicode", "") or "")).strip()
            if not text or _is_size_sensitive_inline_marker(text):
                continue
            style = getattr(same_style_unicode, "pdf_style", None)
            current_size = float(getattr(style, "font_size", 0) or 0)
            if current_size <= 0 or math.isclose(current_size, target_size, rel_tol=0.02, abs_tol=0.12):
                continue
            style.font_size = target_size
            changed += 1
            continue

        char = getattr(item, "pdf_character", None)
        style = getattr(char, "pdf_style", None)
        text = str(getattr(char, "char_unicode", "") or "").strip()
        if style is None or not text or _is_size_sensitive_inline_marker(text):
            continue
        current_size = float(getattr(style, "font_size", 0) or 0)
        if current_size <= 0 or math.isclose(current_size, target_size, rel_tol=0.02, abs_tol=0.12):
            continue
        style.font_size = target_size
        changed += 1
    return changed


def _force_body_retypeset_with_target_font_size(paragraph: Any, target_size: float) -> bool:
    text = _paragraph_plain_text(paragraph)
    if not text or "\n" in str(getattr(paragraph, "unicode", "") or ""):
        return False
    if _PLACEHOLDER_TOKEN_RE.search(text) or _BABELDOC_STYLE_PLACEHOLDER_RE.search(text):
        return False
    if not _looks_like_translated_prose_segment(text):
        return False

    composition = list(getattr(paragraph, "pdf_paragraph_composition", []) or [])
    if not composition:
        return False

    style = _body_retypeset_style(paragraph)
    if style is None or getattr(style, "font_id", None) is None:
        return False

    for item in composition:
        if getattr(item, "pdf_formula", None) is not None or getattr(item, "pdf_line", None) is not None:
            return False
        if (
            getattr(item, "pdf_character", None) is None
            and getattr(item, "pdf_same_style_characters", None) is None
            and getattr(item, "pdf_same_style_unicode_characters", None) is None
        ):
            return False

    from babeldoc.format.pdf.document_il.il_version_1 import PdfParagraphComposition
    from babeldoc.format.pdf.document_il.il_version_1 import PdfSameStyleUnicodeCharacters

    style = copy.deepcopy(style)
    style.font_size = target_size
    comp = PdfParagraphComposition()
    comp.pdf_same_style_unicode_characters = PdfSameStyleUnicodeCharacters(
        pdf_style=style,
        unicode=text,
    )
    paragraph.pdf_paragraph_composition = [comp]
    paragraph.unicode = text
    return True


def _body_retypeset_style(paragraph: Any) -> Any | None:
    style_weights: list[tuple[int, Any]] = []
    for item in getattr(paragraph, "pdf_paragraph_composition", []) or []:
        same_style_unicode = getattr(item, "pdf_same_style_unicode_characters", None)
        if same_style_unicode is not None:
            text = str(getattr(same_style_unicode, "unicode", "") or "")
            style = getattr(same_style_unicode, "pdf_style", None)
            if text and style is not None:
                style_weights.append((_display_width(text), style))
            continue

        same_style = getattr(item, "pdf_same_style_characters", None)
        if same_style is not None:
            chars = list(getattr(same_style, "pdf_character", []) or [])
            style = getattr(same_style, "pdf_style", None)
            if chars and style is not None:
                style_weights.append((len(chars), style))
            continue

        char = getattr(item, "pdf_character", None)
        style = getattr(char, "pdf_style", None)
        text = str(getattr(char, "char_unicode", "") or "")
        if text and style is not None:
            style_weights.append((1, style))

    if style_weights:
        return max(style_weights, key=lambda item: item[0])[1]
    return getattr(paragraph, "pdf_style", None)


def _weighted_median_size(runs: list[tuple[float, int]]) -> float:
    total = sum(weight for _size, weight in runs)
    midpoint = total / 2.0
    cumulative = 0
    for size, weight in sorted(runs, key=lambda item: item[0]):
        cumulative += weight
        if cumulative >= midpoint:
            return size
    return runs[-1][0]


def _paragraph_plain_text(paragraph: Any) -> str:
    text = str(getattr(paragraph, "unicode", "") or "")
    text = _BABELDOC_STYLE_PLACEHOLDER_RE.sub("", text)
    text = re.sub(r"<style\b[^>]*>|</style>", "", text)
    return _SPACE_COLLAPSE_RE.sub(" ", text).strip()


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] + ((values[upper] - values[lower]) * fraction)


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


def _looks_like_translatable_fallback_line_text(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not normalized or not _SPACE_COLLAPSE_RE.search(normalized):
        return False
    return bool(re.search(r"[a-z]", normalized))


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


def _looks_like_dot_leader_fragment(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    return len(normalized) >= 8 and re.fullmatch(r"[.\u00b7\u2026\s]+", normalized) is not None


def _supports_visual_line_split(paragraph: Any) -> bool:
    return getattr(paragraph, "layout_label", None) == "fallback_line"


def _split_paragraph_by_visual_lines(paragraph: Any, *, symbol_font_ids: frozenset[str] = frozenset()) -> list[Any]:
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
            rebuilt_text = _rebuild_fallback_line_text(split_paragraph, symbol_font_ids=symbol_font_ids)
            if rebuilt_text:
                split_paragraph.unicode = rebuilt_text
            if hasattr(split_paragraph, "debug_id") and getattr(split_paragraph, "debug_id", None):
                split_paragraph.debug_id = f"{split_paragraph.debug_id}:vline:{split_index}"
            split_paragraph.optimal_scale = None
            split_paragraphs.append(split_paragraph)
            split_index += 1
    return split_paragraphs


def _wrapped_same_line_tail_groups(
    paragraph: Any,
) -> list[tuple[list[Any], tuple[float, float, float, float]]] | None:
    composition = list(getattr(paragraph, "pdf_paragraph_composition", []) or [])
    if not composition:
        return None
    line_items: list[tuple[Any, tuple[float, float, float, float]]] = []
    for item in composition:
        line_items.extend(_split_composition_item_by_visual_lines(item))
    if len(line_items) < 2:
        return None
    ordered_items = sorted(line_items, key=lambda item: _visual_line_item_sort_key(item[1]))
    grouped_lines: list[dict[str, Any]] = []
    for item, rect in ordered_items:
        if grouped_lines and _same_visual_line(grouped_lines[-1]["rect"], rect):
            grouped_lines[-1]["items"].append((item, rect))
            grouped_lines[-1]["rect"] = _rect_union([grouped_lines[-1]["rect"], rect])
            continue
        grouped_lines.append({"items": [(item, rect)], "rect": rect})
    if len(grouped_lines) < 2:
        return None
    groups: list[tuple[list[Any], tuple[float, float, float, float]]] = []
    for group in grouped_lines:
        ordered_group = sorted(group["items"], key=lambda fragment: fragment[1][0])
        items = [item for item, _rect in ordered_group]
        rect = _rect_union([rect for _item, rect in ordered_group])
        if rect is None:
            return None
        groups.append((items, rect))
    if not _looks_like_wrapped_same_line_tail(paragraph, groups):
        return None
    return groups


def _looks_like_wrapped_same_line_tail(
    paragraph: Any,
    groups: list[tuple[list[Any], tuple[float, float, float, float]]],
) -> bool:
    if len(groups) < 2:
        return False
    paragraph_rect = _box_rect(getattr(paragraph, "box", None))
    if paragraph_rect is None:
        return False
    text = str(getattr(paragraph, "unicode", "") or "")
    if not _looks_like_prose_fragment(text):
        return False
    first_items, first_rect = groups[0]
    second_items, second_rect = groups[1]
    first_text = _composition_text(first_items).strip()
    second_text = _composition_text(second_items).strip()
    if not first_text or not second_text:
        return False
    first_height = max(first_rect[3] - first_rect[1], 1.0)
    second_height = max(second_rect[3] - second_rect[1], 1.0)
    if first_rect[1] <= second_rect[1] + max(first_height, second_height) * 0.45:
        return False
    if first_rect[0] <= paragraph_rect[0] + max(10.0, first_height * 1.2):
        return False
    if abs(second_rect[0] - paragraph_rect[0]) > max(8.0, second_height * 0.8):
        return False
    return True


def _split_paragraph_by_composition_groups(
    paragraph: Any,
    groups: list[tuple[list[Any], tuple[float, float, float, float]]] | None,
) -> list[Any]:
    if not groups or len(groups) < 2:
        return [paragraph]
    split_paragraphs = []
    for index, (items, rect) in enumerate(groups, start=1):
        split_paragraph = copy.deepcopy(paragraph)
        split_paragraph.pdf_paragraph_composition = items
        split_paragraph.unicode = _composition_text(items)
        _set_box_rect(getattr(split_paragraph, "box", None), rect)
        if hasattr(split_paragraph, "debug_id") and getattr(split_paragraph, "debug_id", None):
            split_paragraph.debug_id = f"{split_paragraph.debug_id}:wrapped_tail:{index}"
        split_paragraph.optimal_scale = None
        split_paragraphs.append(split_paragraph)
    return split_paragraphs


def _pop_merge_left_neighbor_for_wrapped_tail(
    rewritten: list[Any],
    tail_first_part: Any,
    hook_context: BabeldocHookContext,
) -> Any | None:
    if not rewritten:
        return None
    left = rewritten[-1]
    left_record = hook_context._record_for_paragraph(left)
    right_record = hook_context._record_for_paragraph(tail_first_part)
    guard = hook_context._guard_merge_records(left_record, right_record)
    if guard.get("guard_decision") == "rejected":
        return None
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(tail_first_part, "box", None))
    if left_rect is None or right_rect is None:
        return None
    if not _same_visual_line(left_rect, right_rect):
        return None
    mergeable_line_fragment = _looks_like_mergeable_line_fragment(
        str(getattr(left, "unicode", "") or ""),
        str(getattr(tail_first_part, "unicode", "") or ""),
    )
    inline_decimal_continuation = _looks_like_inline_decimal_continuation(left, tail_first_part)
    if not mergeable_line_fragment and not inline_decimal_continuation:
        return None
    baseline_ok, _reason = _same_baseline_close_gap(left_rect, right_rect)
    if not baseline_ok:
        return None
    rewritten.pop()
    merged = copy.deepcopy(left)
    _merge_paragraphs(merged, tail_first_part, separator="" if inline_decimal_continuation else None)
    hook_context._focus_postprocess_paragraph(merged)
    return merged


def _should_split_visual_line_groups(paragraph: Any, grouped_lines: list[dict[str, Any]]) -> bool:
    layout_label = getattr(paragraph, "layout_label", None)
    if layout_label != "fallback_line":
        return False
    source_text = unicodedata.normalize("NFKC", str(getattr(paragraph, "unicode", "") or "")).strip()
    if not _looks_like_splitworthy_multiline_fallback_text(source_text):
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


def _rebuild_fallback_line_text(paragraph: Any, *, symbol_font_ids: frozenset[str] | set[str] | None = None) -> str | None:
    chars = _collect_fallback_line_chars(paragraph)
    if len(chars) < 2:
        return None
    if not _looks_like_single_line_fallback_label(paragraph, chars):
        return None
    resolved_symbol_font_ids = symbol_font_ids
    if resolved_symbol_font_ids is None:
        resolved_symbol_font_ids = frozenset()
    rebuilt = _rebuild_compact_technical_label_text(paragraph, chars, symbol_font_ids=frozenset(resolved_symbol_font_ids))
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


def _rebuild_compact_technical_label_text(
    paragraph: Any,
    chars: list[Any],
    *,
    symbol_font_ids: frozenset[str],
) -> str | None:
    ordered = _sort_compact_technical_label_chars(chars)
    if len(ordered) < 2:
        return None
    has_semantic_repair = _has_symbol_glyph_unit_repair(ordered, symbol_font_ids) or _has_i2c_superscript_geometry(ordered)
    if not has_semantic_repair:
        return None
    if not _is_compact_technical_label_candidate(paragraph, ordered, has_semantic_repair=has_semantic_repair):
        return None
    rebuilt = _fallback_line_text_from_chars(ordered, symbol_font_ids=symbol_font_ids).strip()
    if not rebuilt:
        return None
    return _normalize_compact_technical_label_text(rebuilt, ordered)


def _is_compact_technical_label_candidate(paragraph: Any, chars: list[Any], *, has_semantic_repair: bool = False) -> bool:
    layout_label = getattr(paragraph, "layout_label", None)
    if layout_label not in {"fallback_line", "figure_caption"}:
        return False
    source_text = unicodedata.normalize("NFKC", str(getattr(paragraph, "unicode", "") or "")).strip()
    compact = _SPACE_COLLAPSE_RE.sub("", source_text)
    if not compact or len(compact) > 48:
        return False
    if len(chars) < 4 and not has_semantic_repair:
        return False
    if "\n" in source_text:
        return False
    if has_semantic_repair:
        return True
    technical_signals = (
        _TECHNICAL_IDENTIFIER_RE.search(source_text),
        _TECHNICAL_NUMBER_UNIT_RE.search(source_text),
        _TECHNICAL_RATIO_TOKEN_RE.search(source_text),
        _TECHNICAL_UNIT_RE.search(source_text),
        re.search(r"[=()/±°^]|[A-Z]\d", source_text),
        _has_i2c_superscript_geometry(_sort_compact_technical_label_chars(chars)),
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


def _normalize_compact_technical_label_text(text: str, chars: list[Any]) -> str:
    normalized = _normalize_fallback_line_token_spacing(text)
    if _has_i2c_superscript_geometry(chars):
        normalized = re.sub(r"(?<![A-Za-z])I\s*(?:2\s*C|C\s*2)(?![A-Za-z])", "I2C", normalized)
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


def _fallback_line_text_from_chars(chars: list[Any], *, symbol_font_ids: frozenset[str] = frozenset()) -> str:
    parts: list[str] = []
    previous = None
    for index, char in enumerate(chars):
        current_text = _fallback_line_semantic_char_text(chars, index, symbol_font_ids)
        if not current_text:
            previous = char
            continue
        if previous is not None and _should_insert_fallback_line_space(previous, char, current_text):
            parts.append(" ")
        parts.append(current_text)
        previous = char
    normalized = _normalize_fallback_line_token_spacing("".join(parts))
    if _has_i2c_superscript_geometry(chars):
        normalized = re.sub(r"(?<![A-Za-z])I\s*(?:2\s*C|C\s*2)(?![A-Za-z])", "I2C", normalized)
    return normalized


def _fallback_line_semantic_char_text(chars: list[Any], index: int, symbol_font_ids: frozenset[str]) -> str:
    char = chars[index]
    text = str(getattr(char, "char_unicode", "") or "")
    if not text or not _uses_symbol_font(char, symbol_font_ids):
        return text
    if text == "m" and _symbol_m_is_micro_unit(chars, index):
        return "µ"
    if text == "W" and _symbol_w_is_ohm_unit(chars, index):
        return "Ω"
    return text


def _has_symbol_glyph_unit_repair(chars: list[Any], symbol_font_ids: frozenset[str]) -> bool:
    for index, char in enumerate(chars):
        text = str(getattr(char, "char_unicode", "") or "")
        if text and _fallback_line_semantic_char_text(chars, index, symbol_font_ids) != text:
            return True
    return False


def _uses_symbol_font(char: Any, symbol_font_ids: frozenset[str]) -> bool:
    font_id = getattr(getattr(char, "pdf_style", None), "font_id", None)
    return font_id is not None and str(font_id) in symbol_font_ids


def _symbol_m_is_micro_unit(chars: list[Any], index: int) -> bool:
    right = _next_non_space_char(chars, index)
    if right is None:
        return False
    right_text = str(getattr(right, "char_unicode", "") or "")
    if right_text not in {"F", "A", "V", "s", "S"}:
        return False
    return _chars_are_unit_neighbors(chars[index], right)


def _symbol_w_is_ohm_unit(chars: list[Any], index: int) -> bool:
    left = _previous_non_space_char(chars, index)
    if left is None:
        return False
    left_text = str(getattr(left, "char_unicode", "") or "")
    if not (left_text.isdigit() or left_text in {"k", "K", "M"}):
        return False
    return _chars_are_unit_neighbors(left, chars[index])


def _previous_non_space_char(chars: list[Any], index: int) -> Any | None:
    for candidate in reversed(chars[:index]):
        if str(getattr(candidate, "char_unicode", "") or "").strip():
            return candidate
    return None


def _next_non_space_char(chars: list[Any], index: int) -> Any | None:
    for candidate in chars[index + 1 :]:
        if str(getattr(candidate, "char_unicode", "") or "").strip():
            return candidate
    return None


def _chars_are_unit_neighbors(left: Any, right: Any) -> bool:
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    if left_rect is None or right_rect is None:
        return False
    gap = right_rect[0] - left_rect[2]
    if gap < -0.7:
        return True
    font_sizes = []
    for char in (left, right):
        size = float(getattr(getattr(char, "pdf_style", None), "font_size", 0) or 0)
        if size > 0:
            font_sizes.append(size)
    font_size = min(font_sizes) if font_sizes else 7.0
    return gap <= max(1.8, font_size * 0.32)


def _has_i2c_superscript_geometry(chars: list[Any]) -> bool:
    non_space = [char for char in chars if str(getattr(char, "char_unicode", "") or "").strip()]
    for index, char in enumerate(non_space):
        if str(getattr(char, "char_unicode", "") or "") != "I":
            continue
        next_chars = non_space[index + 1 : index + 3]
        if len(next_chars) < 2:
            continue
        texts = [str(getattr(candidate, "char_unicode", "") or "") for candidate in next_chars]
        if texts == ["2", "C"] and _looks_like_superscript_between_i_and_c(char, next_chars[0], next_chars[1]):
            return True
        if texts == ["C", "2"] and _looks_like_superscript_between_i_and_c(char, next_chars[1], next_chars[0]):
            return True
    return False


def _looks_like_superscript_between_i_and_c(i_char: Any, two_char: Any, c_char: Any) -> bool:
    i_rect = _box_rect(getattr(i_char, "box", None))
    two_rect = _box_rect(getattr(two_char, "box", None))
    c_rect = _box_rect(getattr(c_char, "box", None))
    if i_rect is None or two_rect is None or c_rect is None:
        return False
    base_top = min(i_rect[1], c_rect[1])
    base_height = max(i_rect[3] - i_rect[1], c_rect[3] - c_rect[1], 1.0)
    two_height = two_rect[3] - two_rect[1]
    if two_height > base_height * 0.9:
        return False
    expanded_top = base_top - base_height * 0.45
    expanded_bottom = max(i_rect[3], c_rect[3]) + base_height * 0.45
    two_center_y = (two_rect[1] + two_rect[3]) / 2
    if not expanded_top <= two_center_y <= expanded_bottom:
        return False
    i_center = (i_rect[0] + i_rect[2]) / 2
    c_center = (c_rect[0] + c_rect[2]) / 2
    two_center = (two_rect[0] + two_rect[2]) / 2
    if c_center - i_center > max(14.0, base_height * 2.2):
        return False
    return i_center <= two_center <= c_center + base_height * 0.35


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
    if left_last in {"k", "K", "M"} and right_first in {"Ω", "Ω"}:
        return True
    if left_last in "(/_-" or right_first in "/_-)":
        return True
    if _looks_like_compact_technical_token_join(left, right):
        return True
    if len(left) == 1 or len(right) == 1:
        return _looks_like_short_pin_or_bus_token_join(left, right)
    if left_last.isupper() and right_first.isupper() and min(len(left), len(right)) <= 2:
        return True
    return False


def _looks_like_short_pin_or_bus_token_join(left: str, right: str) -> bool:
    combined = f"{left}{right}"
    if not re.fullmatch(r"[A-Za-z0-9]+", combined):
        return False
    if _TECHNICAL_IDENTIFIER_RE.fullmatch(combined):
        return True
    if re.fullmatch(r"(?:AIN|GPIO|ADDR|ALERT|SCL|SDA|VDD|VSS|GND|A|D)\d{1,2}", combined, re.IGNORECASE):
        return True
    if re.fullmatch(r"\d{1,2}(?:V|A|F|S|Hz|kHz|MHz|SPS)", combined, re.IGNORECASE):
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
                candidate_text = unicodedata.normalize("NFKC", candidate.text).strip()
                if _looks_like_translatable_fallback_line_text(candidate_text):
                    continue
                if _rects_share_fallback_line_band(base_rect, candidate.rect):
                    protected.add(candidate.paragraph_id)
    return protected


def _detect_schematic_figure_label_ids(records: list[_ParagraphRecord]) -> set[str]:
    grouped: dict[tuple[int, int | str | None], list[_ParagraphRecord]] = {}
    for record in records:
        if record.layout_label != "fallback_line" or record.rect is None:
            continue
        grouped.setdefault((record.page_number, record.xobj_id), []).append(record)
    preserved: set[str] = set()
    for group_records in grouped.values():
        anchors = [record for record in group_records if _looks_like_schematic_anchor_label(record)]
        if len(anchors) < 6:
            continue
        cluster_rect = _rect_union([record.rect for record in anchors])
        if cluster_rect is None:
            continue
        for record in group_records:
            if record.paragraph_id in preserved:
                continue
            if not _looks_like_schematic_damaged_label(record):
                continue
            if _inside_schematic_label_cluster(record.rect, cluster_rect):
                preserved.add(record.paragraph_id)
    return preserved


def _looks_like_schematic_anchor_label(record: _ParagraphRecord) -> bool:
    text = unicodedata.normalize("NFKC", record.text).strip()
    compact = _SPACE_COLLAPSE_RE.sub("", text)
    if not compact:
        return False
    if _TECHNICAL_IDENTIFIER_RE.search(compact):
        return True
    if _TECHNICAL_NUMBER_UNIT_RE.search(text) or _TECHNICAL_RATIO_TOKEN_RE.search(text):
        return True
    if re.fullmatch(r"(?:AIN|SCL|SDA|VDD|GND|ADDR|ALERT|JTAG|ON|OFF|SAMPLE|S\d+|DOUT/DRDY|DIN|CLK)[A-Z0-9./() -]*", compact, re.IGNORECASE):
        return True
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?V", compact, re.IGNORECASE):
        return True
    return False


def _looks_like_schematic_damaged_label(record: _ParagraphRecord) -> bool:
    if record.rect is None:
        return False
    text = unicodedata.normalize("NFKC", record.text).strip()
    compact = _SPACE_COLLAPSE_RE.sub("", text)
    if not compact:
        return False
    x1, y1, x2, y2 = record.rect
    width = x2 - x1
    height = y2 - y1
    if height > 9.5 or width > 90.0:
        return False
    if _looks_like_translatable_fallback_line_text(text) and not _looks_like_schematic_extraction_noise(text):
        return False
    if _is_preserve_candidate(record):
        return True
    return _looks_like_schematic_extraction_noise(text)


def _looks_like_schematic_extraction_noise(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    compact = _SPACE_COLLAPSE_RE.sub("", normalized)
    if not compact:
        return False
    if re.search(r"\bF\d{2,}[A-Za-z]\b", normalized):
        return True
    if re.search(r"\b[A-Z]{1,4}/[A-Z]\s+[A-Z]\b", normalized):
        return True
    if re.search(r"\b[A-Z]\s+[A-Z0-9/]\s+[A-Z]\b", normalized):
        return True
    if re.search(r"\b[A-Za-z]+[A-Z][a-z]*e\b", compact) and re.search(r"\b[A-Z]\s+[A-Z]", normalized):
        return True
    return False


def _inside_schematic_label_cluster(
    rect: tuple[float, float, float, float],
    cluster_rect: tuple[float, float, float, float],
) -> bool:
    x1, y1, x2, y2 = cluster_rect
    width = max(x2 - x1, 1.0)
    height = max(y2 - y1, 1.0)
    expanded = (
        x1 - max(18.0, width * 0.08),
        y1 - max(14.0, height * 0.16),
        x2 + max(18.0, width * 0.08),
        y2 + max(14.0, height * 0.16),
    )
    center_x = (rect[0] + rect[2]) / 2
    center_y = (rect[1] + rect[3]) / 2
    return expanded[0] <= center_x <= expanded[2] and expanded[1] <= center_y <= expanded[3]


def _is_fallback_line_underscore_band_paragraph(paragraph_or_record: Any) -> bool:
    layout_label = getattr(paragraph_or_record, "layout_label", None)
    if layout_label != "fallback_line":
        return False
    text = unicodedata.normalize("NFKC", str(getattr(paragraph_or_record, "unicode", None) or getattr(paragraph_or_record, "text", "") or "")).strip()
    if not text:
        return False
    if _looks_like_translatable_fallback_line_text(text):
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
