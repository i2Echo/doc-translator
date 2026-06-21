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
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
_ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_TRAILING_UNIT_PARENS_RE = re.compile(r"[\(（]([^()（）]+)[\)）]\s*$")
_TECHNICAL_NUMBER_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+±]?\d+(?:\.\d+)?\s*(?:MΩ|kΩ|Ω|µA|uA|mA|µV|uV|mV|V|°C|℃|dB|kHz|MHz|Hz|SPS|mW|W|pF|nF|µF|uF|%)\b"
)
_TECHNICAL_UNIT_RE = re.compile(r"(?<![A-Za-z])(?:MΩ|kΩ|Ω|µA|uA|mA|µV|uV|mV|V|°C|℃|dB|kHz|MHz|Hz|SPS|mW|W|pF|nF|µF|uF|%)(?![A-Za-z])")
_AXIS_LABEL_TEXT_RE = re.compile(
    r"^[A-Za-z][A-Za-z\s/+&-]{1,70}\s*"
    r"\((?:MΩ|kΩ|Ω|µA|uA|mA|µV|uV|mV|V|°C|℃|dB|kHz|MHz|Hz|SPS|mW|W|pF|nF|µF|uF|LSB|ppm|FSR|%)"
    r"(?:\s+of\s+FSR)?\)$"
)
_TECHNICAL_IDENTIFIER_RE = re.compile(
    r"\b(?:VDD|VSS|VCC|VREF|VIN|VOUT|VIH|VIL|VOH|VOL|GND|IOL|IOH|ISINK|IL|IH|TA|TJ|TS|TSTG|FCM|DR|PGA|ADC|I2C|SCL|SDA|ADDR|TTL|TI|DIV|FS|LM\d+|ADS\d+)\b",
    re.IGNORECASE,
)
_SINGLE_LETTER_TECHNICAL_RE = re.compile(r"(?<![A-Za-z])(?:R[ABC]?|C)(?![A-Za-z])")
_TECHNICAL_TRANSLATION_REPLACEMENTS = (
    (re.compile(r"(?<=\d)\s*兆欧(?:姆)?"), "MΩ"),
    (re.compile(r"(?<=\d)\s*千欧(?:姆)?"), "kΩ"),
    (re.compile(r"(?<=\d)\s*欧姆"), "Ω"),
    (re.compile(r"(?<=\d)\s*毫安"), "mA"),
    (re.compile(r"(?<=\d)\s*微安"), "µA"),
    (re.compile(r"(?<=\d)\s*纳安"), "nA"),
    (re.compile(r"(?<=\d)\s*毫伏"), "mV"),
    (re.compile(r"(?<=\d)\s*微伏"), "µV"),
    (re.compile(r"(?<=\d)\s*(?:伏特|伏)"), "V"),
    (re.compile(r"(?<=\d)\s*(?:摄氏度|℃)"), "°C"),
    (re.compile(r"(?<=\d)\s*分贝"), "dB"),
    (re.compile(r"(?<=\d)\s*兆赫兹"), "MHz"),
    (re.compile(r"(?<=\d)\s*千赫兹"), "kHz"),
    (re.compile(r"(?<=\d)\s*赫兹"), "Hz"),
    (re.compile(r"(?<=\d)\s*微法"), "µF"),
    (re.compile(r"(?<=\d)\s*纳法"), "nF"),
    (re.compile(r"(?<=\d)\s*皮法"), "pF"),
)
_TECHNICAL_WORD_REPLACEMENTS = (
    (re.compile(r"电容(?=\s*[=A-Z0-9±+\-.,;:/)]|$)"), "C"),
    (re.compile(r"电阻\s*A"), "RA"),
    (re.compile(r"电阻\s*B"), "RB"),
)
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

    def classify_document(self, document: Any) -> None:
        records = self._collect_records(document)
        self.records_by_id = {record.paragraph_id: record for record in records}
        self.records_by_object_id = {record.object_id: record for record in records}

        for record in records:
            if _is_toc_candidate(record, len(getattr(document, "page", []) or [])):
                _mark(record, "toc_entry", "translate_title_preserve_locator", 0.9, ("dot leader with trailing page number",))
                continue
            if _is_vertical_candidate(record):
                _mark(record, "vertical_label", "preserve", 0.9, ("vertical or high-narrow paragraph",))
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

    def should_force_plain_text(self, paragraph: Any) -> bool:
        text = str(getattr(paragraph, "unicode", "") or "")
        record = self._record_for_paragraph(paragraph)
        reason = None
        if _has_inline_numbered_markers(text):
            reason = "inline_numbered_markers"
        if reason is None:
            return False
        self.applied_events.append(
            {
                "action": "force_plain_text",
                "paragraph_id": record.paragraph_id if record is not None else None,
                "role": record.role if record is not None else "body",
                "reason": reason,
            }
        )
        return True

    def translation_text_override(self, paragraph: Any, text: str) -> str:
        record = self._record_for_paragraph(paragraph)
        if record is None:
            return text
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
            if _has_inline_numbered_markers(record.text):
                translated_text = _strip_babeldoc_style_placeholders(translated_text)
        translated_text = _restore_common_technical_translations(source_text, translated_text)
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
        replacements: list[tuple[int, int]] = []
        for pattern in (_TECHNICAL_NUMBER_UNIT_RE, _TECHNICAL_IDENTIFIER_RE, _SINGLE_LETTER_TECHNICAL_RE, _TECHNICAL_UNIT_RE):
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(start < existing_end and end > existing_start for existing_start, existing_end in replacements):
                    continue
                replacements.append((start, end))
        if not replacements:
            return text

        replacements.sort()
        pieces: list[str] = []
        protected: list[tuple[str, str]] = []
        cursor = 0
        for index, (start, end) in enumerate(replacements):
            token = text[start:end]
            placeholder = f"DTPRESERVE{index:03d}"
            pieces.append(text[cursor:start])
            pieces.append(placeholder)
            protected.append((placeholder, token))
            cursor = end
        pieces.append(text[cursor:])
        self._protected_tokens[record.paragraph_id] = protected
        self.applied_events.append(
            {
                "action": "protect_technical_tokens",
                "paragraph_id": record.paragraph_id,
                "role": record.role,
                "count": len(protected),
            }
        )
        return "".join(pieces)

    def _restore_protected_tokens(self, record: _ParagraphRecord, translated_text: str) -> str:
        protected = self._protected_tokens.get(record.paragraph_id)
        if not protected:
            return translated_text
        restored = translated_text
        for placeholder, token in protected:
            restored = re.sub(re.escape(placeholder), token, restored, flags=re.IGNORECASE)
        return restored

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

    def merge_same_line_fragments_before_translation(self, document: Any) -> bool:
        merged = 0
        samples = []
        for page in getattr(document, "page", []) or []:
            paragraphs = list(getattr(page, "pdf_paragraph", []) or [])
            if len(paragraphs) < 2:
                continue
            rewritten = []
            index = 0
            while index < len(paragraphs):
                current = paragraphs[index]
                while index + 1 < len(paragraphs) and self._should_merge_same_line_fragments(current, paragraphs[index + 1]):
                    right = paragraphs[index + 1]
                    if len(samples) < 8:
                        samples.append(
                            {
                                "left": str(getattr(current, "unicode", "") or "")[:80],
                                "right": str(getattr(right, "unicode", "") or "")[:80],
                                "rect": _box_rect(getattr(current, "box", None)),
                            }
                        )
                    _merge_paragraphs(current, right)
                    merged += 1
                    index += 1
                rewritten.append(current)
                index += 1
            page.pdf_paragraph = rewritten

        if merged:
            self.applied_events.append(
                {
                    "action": "merge_same_line_fragments_before_translation",
                    "pairs": merged,
                    "samples": samples,
                }
            )
        return merged > 0

    def _should_merge_same_line_fragments(self, left: Any, right: Any) -> bool:
        left_record = self._record_for_paragraph(left)
        right_record = self._record_for_paragraph(right)
        if left_record is None or right_record is None:
            return False
        if left_record.role in {"toc_entry", "vertical_label", "running_edge_text"}:
            return False
        if right_record.role in {"toc_entry", "vertical_label", "running_edge_text"}:
            return False
        if _is_edge_band(left_record) or _is_edge_band(right_record):
            return False
        if getattr(left, "xobj_id", None) != getattr(right, "xobj_id", None):
            return False

        left_text = str(getattr(left, "unicode", "") or "")
        right_text = str(getattr(right, "unicode", "") or "")
        if not _looks_like_mergeable_line_fragment(left_text, right_text):
            return False

        left_rect = _box_rect(getattr(left, "box", None))
        right_rect = _box_rect(getattr(right, "box", None))
        if left_rect is None or right_rect is None:
            return False
        return _same_baseline_close_gap(left_rect, right_rect)

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
            if source_text is None or source_rect is None:
                continue
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

    def _translate_axis_label_text(self, source_text: str, translation_config: Any) -> str:
        with self._lock:
            cached = self._axis_label_translation_cache.get(source_text)
        if cached is not None:
            return cached
        translated = translation_config.translator.translate(source_text, ignore_cache=False)
        translated = _restore_common_technical_translations(source_text, translated)
        translated = _restore_axis_label_unit(source_text, translated)
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
        return False
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
) -> bool:
    if right_rect[0] < left_rect[0]:
        return False
    left_height = max(left_rect[3] - left_rect[1], 1.0)
    right_height = max(right_rect[3] - right_rect[1], 1.0)
    overlap = min(left_rect[3], right_rect[3]) - max(left_rect[1], right_rect[1])
    if overlap / min(left_height, right_height) < 0.62:
        return False
    center_delta = abs(((left_rect[1] + left_rect[3]) / 2) - ((right_rect[1] + right_rect[3]) / 2))
    if center_delta > max(left_height, right_height) * 0.45:
        return False
    gap = right_rect[0] - left_rect[2]
    return -1.0 <= gap <= max(4.0, min(left_height, right_height) * 0.55)


def _merge_paragraphs(left: Any, right: Any) -> None:
    left_rect = _box_rect(getattr(left, "box", None))
    right_rect = _box_rect(getattr(right, "box", None))
    separator = ""
    if left_rect is not None and right_rect is not None and right_rect[0] - left_rect[2] > 1.5:
        separator = " "
    left.unicode = f"{str(getattr(left, 'unicode', '') or '')}{separator}{str(getattr(right, 'unicode', '') or '')}"
    left.pdf_paragraph_composition = list(getattr(left, "pdf_paragraph_composition", []) or []) + list(
        getattr(right, "pdf_paragraph_composition", []) or []
    )
    if left_rect is not None and right_rect is not None:
        _set_box_rect(getattr(left, "box", None), _rect_union([left_rect, right_rect]))
    left.optimal_scale = None


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
    normalized = re.sub(r"(?<=[A-Za-z])[^\w\s'-]+(?=[A-Za-z])", " ", normalized)
    normalized = re.sub(r"(?<=[A-Za-z])(of|and|vs|per|from|to|in)(?=[A-Z])", r" \1 ", normalized)
    normalized = _ACRONYM_BOUNDARY_RE.sub(" ", _CAMEL_BOUNDARY_RE.sub(" ", normalized))
    normalized = _SPACE_COLLAPSE_RE.sub(" ", normalized)
    if not 8 <= len(normalized) <= 48:
        return None
    words = normalized.split(" ")
    if not 2 <= len(words) <= 4:
        return None
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", word) for word in words):
        return None
    if any(len(word) == 1 for word in words):
        return None
    if not any(len(word) >= 5 for word in words):
        return None
    letters = sum(1 for char in normalized if char.isalpha())
    if letters < 8:
        return None
    return normalized


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
        char = getattr(composition, "pdf_character", None)
        if char is not None:
            chars.append(char)
        formula = getattr(composition, "pdf_formula", None)
        if formula is not None:
            chars.extend(getattr(formula, "pdf_character", []) or [])
    return chars


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
    if _looks_like_tabular_vertical_column(segment):
        return False
    return _looks_like_axis_label_segment_text(stripped)


def _looks_like_axis_measurement_label(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
    normalized = _SPACE_COLLAPSE_RE.sub(" ", normalized)
    return bool(_AXIS_LABEL_TEXT_RE.fullmatch(normalized))


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


def _restore_common_technical_translations(source_text: str, translated_text: str) -> str:
    restored = translated_text
    for pattern, replacement in _TECHNICAL_TRANSLATION_REPLACEMENTS:
        restored = pattern.sub(lambda match, value=replacement: f"{' ' if match.group(0)[0].isspace() else ''}{value}", restored)
    for pattern, replacement in _TECHNICAL_WORD_REPLACEMENTS:
        if replacement in source_text:
            restored = pattern.sub(replacement, restored)
    if "GND" in source_text:
        restored = restored.replace("接地", "GND")
    return restored


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
