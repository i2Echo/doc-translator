from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import fitz
from docx import Document

from doc_translator.models import TranslationJob
from doc_translator.storage import file_checksum


DOCX_PREVIEW_PARAGRAPH_LIMIT = 8
DOCX_PREVIEW_CHAR_LIMIT = 2200
PDF_MIN_REDRAW_FONT_SIZE = 6.0
PDF_EDITOR_MIN_FONT_SIZE = 8.0
PDF_BLOCK_MERGE_IOU_THRESHOLD = 0.3
PDF_BLOCK_MERGE_VERTICAL_DISTANCE = 5.0
PDF_BLOCK_MERGE_HORIZONTAL_GAP = 18.0
PDF_BLOCK_MERGE_MIN_HORIZONTAL_OVERLAP_RATIO = 0.2
PDF_TABLE_MIN_ROWS = 2
PDF_TABLE_MIN_COLS = 2
PDF_TABLE_MIN_CELLS = 3
PDF_UNKNOWN_SPACING_PATTERN = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+")
PDF_ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]+")
PDF_UNKNOWN_GLYPH_BLOCK_PATTERN = re.compile(r"[\u25a0-\u25ff\u2610\u2751\u2b1a\u2b1c\ufffd]+")
PDF_MALFORMED_MULTIPLICATION_PATTERN = re.compile(r"(?<=\d)\s*[xX✕✖╳⨯*＊]\s*(?=\d)")


@dataclass(slots=True)
class PdfPreviewFragment:
    rect: fitz.Rect
    text: str
    font_names: list[str] = field(default_factory=list)
    font_sizes: list[float] = field(default_factory=list)

    @property
    def dominant_font(self) -> str:
        return Counter(self.font_names).most_common(1)[0][0] if self.font_names else _select_pdf_font(self.text)

    @property
    def average_font_size(self) -> float:
        return round(sum(self.font_sizes) / len(self.font_sizes), 2) if self.font_sizes else 12.0


@dataclass(slots=True)
class PdfPreviewWord:
    rect: fitz.Rect
    text: str
    block_index: int
    line_index: int
    word_index: int


def preview_sidecar_path(output_path: str) -> Path:
    path = Path(output_path)
    return path.with_name(f"{path.name}.preview.json")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_pdf_block_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in str(text or "").replace("\r\n", "\n").split("\n")).strip()


def _replace_unknown_spacing_block(match: re.Match[str]) -> str:
    source = match.string
    start, end = match.span()
    previous = source[start - 1] if start > 0 else ""
    following = source[end] if end < len(source) else ""
    if previous and following and not previous.isspace() and not following.isspace():
        return "-"
    return " "


def _sanitize_pdf_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n")
    normalized = PDF_ZERO_WIDTH_PATTERN.sub("", normalized)
    normalized = PDF_UNKNOWN_SPACING_PATTERN.sub(" ", normalized)
    normalized = PDF_UNKNOWN_GLYPH_BLOCK_PATTERN.sub(_replace_unknown_spacing_block, normalized)
    normalized = PDF_MALFORMED_MULTIPLICATION_PATTERN.sub(" × ", normalized)

    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in normalized.split("\n")]
    return _normalize_pdf_block_text("\n".join(lines))


def _has_codepoint_in_ranges(text: str, ranges: tuple[tuple[str, str], ...]) -> bool:
    return any(start <= char <= end for char in text for start, end in ranges)


def _select_pdf_font(text: str) -> str:
    if _has_codepoint_in_ranges(text, (("\uac00", "\ud7af"), ("\u1100", "\u11ff"), ("\u3130", "\u318f"))):
        return "korea"
    if _has_codepoint_in_ranges(text, (("\u3040", "\u30ff"), ("\u31f0", "\u31ff"))):
        return "japan"
    if _has_codepoint_in_ranges(
        text,
        (
            ("\u3400", "\u4dbf"),
            ("\u4e00", "\u9fff"),
            ("\uf900", "\ufaff"),
            ("\uff00", "\uffef"),
            ("\u0400", "\u04ff"),
        ),
    ):
        return "china-s"
    return "helv"


def _rect_iou(left: fitz.Rect, right: fitz.Rect) -> float:
    intersection_width = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    intersection_height = max(0.0, min(left.y1, right.y1) - max(left.y0, right.y0))
    intersection_area = intersection_width * intersection_height
    if intersection_area <= 0:
        return 0.0

    left_area = max(0.0, left.width) * max(0.0, left.height)
    right_area = max(0.0, right.width) * max(0.0, right.height)
    union_area = left_area + right_area - intersection_area
    return intersection_area / union_area if union_area > 0 else 0.0


def _rect_overlap_ratio(left: fitz.Rect, right: fitz.Rect) -> float:
    intersection_width = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    intersection_height = max(0.0, min(left.y1, right.y1) - max(left.y0, right.y0))
    intersection_area = intersection_width * intersection_height
    left_area = max(0.0, left.width) * max(0.0, left.height)
    return intersection_area / left_area if left_area > 0 else 0.0


def _rect_vertical_gap(left: fitz.Rect, right: fitz.Rect) -> float:
    if left.y1 < right.y0:
        return right.y0 - left.y1
    if right.y1 < left.y0:
        return left.y0 - right.y1
    return 0.0


def _rect_horizontal_gap(left: fitz.Rect, right: fitz.Rect) -> float:
    if left.x1 < right.x0:
        return right.x0 - left.x1
    if right.x1 < left.x0:
        return left.x0 - right.x1
    return 0.0


def _horizontal_overlap_ratio(left: fitz.Rect, right: fitz.Rect) -> float:
    overlap = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    smallest_width = max(min(left.width, right.width), 1.0)
    return overlap / smallest_width


def _should_merge_pdf_fragments(left: PdfPreviewFragment, right: PdfPreviewFragment) -> bool:
    if _rect_iou(left.rect, right.rect) > PDF_BLOCK_MERGE_IOU_THRESHOLD:
        return True

    same_reading_lane = (
        _horizontal_overlap_ratio(left.rect, right.rect) >= PDF_BLOCK_MERGE_MIN_HORIZONTAL_OVERLAP_RATIO
        or _rect_horizontal_gap(left.rect, right.rect) <= PDF_BLOCK_MERGE_HORIZONTAL_GAP
    )
    return _rect_vertical_gap(left.rect, right.rect) <= PDF_BLOCK_MERGE_VERTICAL_DISTANCE and same_reading_lane


def _pdf_fragment_sort_key(fragment: PdfPreviewFragment) -> tuple[float, float]:
    return (round(fragment.rect.y0, 2), round(fragment.rect.x0, 2))


def _merge_pdf_fragment_rects(fragments: list[PdfPreviewFragment]) -> fitz.Rect:
    return fitz.Rect(
        min(fragment.rect.x0 for fragment in fragments),
        min(fragment.rect.y0 for fragment in fragments),
        max(fragment.rect.x1 for fragment in fragments),
        max(fragment.rect.y1 for fragment in fragments),
    )


def _merge_pdf_fragment_texts(fragments: list[PdfPreviewFragment]) -> str:
    ordered = sorted(fragments, key=_pdf_fragment_sort_key)
    merged_text = ""
    previous_fragment: PdfPreviewFragment | None = None

    for fragment in ordered:
        text = fragment.text.strip()
        if not text:
            continue
        if not merged_text:
            merged_text = text
        else:
            separator = "\n" if previous_fragment and _rect_vertical_gap(previous_fragment.rect, fragment.rect) > 1 else " "
            merged_text = f"{merged_text}{separator}{text}"
        previous_fragment = fragment

    return _normalize_pdf_block_text(merged_text)


def _merge_pdf_fragments(fragments: list[PdfPreviewFragment]) -> PdfPreviewFragment:
    return PdfPreviewFragment(
        rect=_merge_pdf_fragment_rects(fragments),
        text=_merge_pdf_fragment_texts(fragments),
        font_names=[font_name for fragment in fragments for font_name in fragment.font_names],
        font_sizes=[font_size for fragment in fragments for font_size in fragment.font_sizes],
    )


def _cluster_pdf_fragments(fragments: list[PdfPreviewFragment]) -> list[PdfPreviewFragment]:
    remaining = sorted(fragments, key=_pdf_fragment_sort_key)
    merged_fragments: list[PdfPreviewFragment] = []

    while remaining:
        cluster = [remaining.pop(0)]
        cluster_changed = True
        while cluster_changed:
            cluster_changed = False
            unmatched: list[PdfPreviewFragment] = []
            for candidate in remaining:
                if any(_should_merge_pdf_fragments(member, candidate) for member in cluster):
                    cluster.append(candidate)
                    cluster_changed = True
                else:
                    unmatched.append(candidate)
            remaining = unmatched

        merged_fragments.append(_merge_pdf_fragments(cluster))

    return sorted(merged_fragments, key=_pdf_fragment_sort_key)


def _extract_pdf_text_fragments(page: fitz.Page) -> list[PdfPreviewFragment]:
    text_dict = page.get_text("dict")
    fragments: list[PdfPreviewFragment] = []

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        lines: list[str] = []
        font_names: list[str] = []
        font_sizes: list[float] = []
        for line in block.get("lines", []):
            line_parts: list[str] = []
            for span in line.get("spans", []):
                span_text = span.get("text", "")
                if not span_text.strip():
                    continue
                line_parts.append(span_text)
                font_name = str(span.get("font", "")).strip()
                if font_name:
                    font_names.append(font_name)
                span_size = span.get("size")
                if isinstance(span_size, (int, float)):
                    font_sizes.append(float(span_size))
            line_text = _sanitize_pdf_text("".join(line_parts))
            if line_text:
                lines.append(line_text)

        text = _normalize_pdf_block_text("\n".join(lines))
        if not text:
            continue

        bbox = fitz.Rect(block.get("bbox", (0, 0, 0, 0)))
        fragments.append(PdfPreviewFragment(rect=bbox, text=text, font_names=font_names, font_sizes=font_sizes))

    return fragments


def _extract_pdf_words(page: fitz.Page | None) -> list[PdfPreviewWord]:
    if page is None:
        return []

    words: list[PdfPreviewWord] = []
    for raw_word in page.get_text("words"):
        text = _sanitize_pdf_text(raw_word[4])
        if not text:
            continue

        words.append(
            PdfPreviewWord(
                rect=fitz.Rect(raw_word[:4]),
                text=text,
                block_index=int(raw_word[5]),
                line_index=int(raw_word[6]),
                word_index=int(raw_word[7]),
            )
        )

    return words


def _extract_page_text_in_rect(
    page: fitz.Page | None,
    rect: fitz.Rect,
    *,
    textpage: fitz.TextPage | None = None,
) -> str:
    if page is None:
        return ""
    return _sanitize_pdf_text(page.get_textbox(rect, textpage=textpage))


def _extract_clipped_words_text_in_rect(
    page: fitz.Page | None,
    rect: fitz.Rect,
    *,
    textpage: fitz.TextPage | None = None,
    padding: float = 1.0,
) -> str:
    if page is None or textpage is None:
        return ""

    clip = fitz.Rect(rect.x0 - padding, rect.y0 - padding, rect.x1 + padding, rect.y1 + padding)
    lines: list[list[str]] = []
    current_line_key: tuple[int, int] | None = None
    current_words: list[str] = []

    for raw_word in page.get_text("words", clip=clip, textpage=textpage):
        line_key = (int(raw_word[5]), int(raw_word[6]))
        if current_line_key is not None and line_key != current_line_key:
            if current_words:
                lines.append(current_words)
            current_words = []

        text = _sanitize_pdf_text(raw_word[4])
        if text:
            current_words.append(text)
        current_line_key = line_key

    if current_words:
        lines.append(current_words)

    extracted_text = _normalize_pdf_block_text("\n".join(" ".join(line).strip() for line in lines if line))
    return extracted_text or _extract_page_text_in_rect(page, rect, textpage=textpage)


def _word_belongs_to_rect(word: PdfPreviewWord, rect: fitz.Rect) -> bool:
    center_x = (word.rect.x0 + word.rect.x1) / 2
    center_y = (word.rect.y0 + word.rect.y1) / 2
    if rect.x0 <= center_x <= rect.x1 and rect.y0 <= center_y <= rect.y1:
        return True
    return _rect_overlap_ratio(word.rect, rect) >= 0.5 or _rect_overlap_ratio(rect, word.rect) >= 0.5


def _extract_words_text_in_rect(words: list[PdfPreviewWord], rect: fitz.Rect) -> str:
    selected_words = [word for word in words if _word_belongs_to_rect(word, rect)]
    if not selected_words:
        return ""

    ordered_words = sorted(
        selected_words,
        key=lambda word: (
            round(word.rect.y0, 2),
            round(word.rect.x0, 2),
            word.block_index,
            word.line_index,
            word.word_index,
        ),
    )

    lines: list[list[str]] = []
    current_line: list[str] = []
    current_top: float | None = None
    current_block: int | None = None
    current_line_index: int | None = None

    for word in ordered_words:
        starts_new_line = (
            current_top is not None
            and (
                abs(word.rect.y0 - current_top) > 2.0
                or word.block_index != current_block
                or word.line_index != current_line_index
            )
        )
        if starts_new_line and current_line:
            lines.append(current_line)
            current_line = []

        current_line.append(word.text)
        current_top = word.rect.y0
        current_block = word.block_index
        current_line_index = word.line_index

    if current_line:
        lines.append(current_line)

    return _normalize_pdf_block_text("\n".join(" ".join(line).strip() for line in lines if line))


def _average_font_size_in_rect(fragments: list[PdfPreviewFragment], rect: fitz.Rect) -> float:
    font_sizes = [
        font_size
        for fragment in fragments
        if _rect_overlap_ratio(fragment.rect, rect) >= 0.5 or _rect_overlap_ratio(rect, fragment.rect) >= 0.5
        for font_size in fragment.font_sizes
    ]
    return round(sum(font_sizes) / len(font_sizes), 2) if font_sizes else 11.0


def _build_pdf_text_blocks(
    fragments: list[PdfPreviewFragment],
    *,
    source_page: fitz.Page | None,
    target_page: fitz.Page | None,
    source_textpage: fitz.TextPage | None,
    target_textpage: fitz.TextPage | None,
) -> list[dict[str, object]]:
    merged_blocks = _cluster_pdf_fragments(fragments)
    return [
        {
            "type": "text",
            "rect": [round(block.rect.x0, 2), round(block.rect.y0, 2), round(block.rect.x1, 2), round(block.rect.y1, 2)],
            "font_name": block.dominant_font,
            "font_size_original": block.average_font_size,
            "font_size_current": block.average_font_size,
            "src_text": _extract_page_text_in_rect(source_page, block.rect, textpage=source_textpage),
            "tgt_text": _extract_page_text_in_rect(target_page, block.rect, textpage=target_textpage),
        }
        for block in merged_blocks
    ]


def _dedupe_sorted_positions(values: list[float], *, tolerance: float = 1.0) -> list[float]:
    deduped: list[float] = []
    for value in sorted(values):
        if deduped and abs(value - deduped[-1]) <= tolerance:
            deduped[-1] = max(deduped[-1], value)
        else:
            deduped.append(value)
    return deduped


def _table_grid_positions(table) -> tuple[list[float], list[float]]:
    x_positions = [float(table.bbox[0]), float(table.bbox[2])]
    y_positions = [float(table.bbox[1]), float(table.bbox[3])]

    for row in table.rows:
        for cell in row.cells:
            if cell is None:
                continue
            x0, y0, x1, y1 = cell
            x_positions.extend([float(x0), float(x1)])
            y_positions.extend([float(y0), float(y1)])

    return _dedupe_sorted_positions(x_positions), _dedupe_sorted_positions(y_positions)


def _grid_index_for_position(positions: list[float], value: float, *, tolerance: float = 1.0) -> int:
    for index, position in enumerate(positions):
        if abs(position - value) <= tolerance:
            return index
    return min(range(len(positions)), key=lambda index: abs(positions[index] - value))


def _fragment_belongs_to_table(fragment: PdfPreviewFragment, table_rects: list[fitz.Rect]) -> bool:
    center_x = (fragment.rect.x0 + fragment.rect.x1) / 2
    center_y = (fragment.rect.y0 + fragment.rect.y1) / 2
    for table_rect in table_rects:
        if table_rect.x0 <= center_x <= table_rect.x1 and table_rect.y0 <= center_y <= table_rect.y1:
            return True
        if _rect_overlap_ratio(fragment.rect, table_rect) >= 0.5:
            return True
    return False


def _extract_pdf_table_blocks(
    editable_page: fitz.Page | None,
    *,
    page_index: int,
    source_page: fitz.Page | None,
    source_textpage: fitz.TextPage | None,
    target_words: list[PdfPreviewWord],
    source_fragments: list[PdfPreviewFragment],
    target_fragments: list[PdfPreviewFragment],
) -> list[dict[str, object]]:
    if editable_page is None:
        return []

    table_blocks: list[dict[str, object]] = []
    for table_index, table in enumerate(editable_page.find_tables().tables, start=1):
        x_positions, y_positions = _table_grid_positions(table)
        rows_count = max(len(y_positions) - 1, 0)
        cols_count = max(len(x_positions) - 1, 0)
        if rows_count < PDF_TABLE_MIN_ROWS or cols_count < PDF_TABLE_MIN_COLS:
            continue

        cells: list[dict[str, object]] = []
        seen_rects: set[tuple[float, float, float, float]] = set()
        font_fragments = target_fragments or source_fragments
        for row in table.rows:
            for cell in row.cells:
                if cell is None:
                    continue

                rect = fitz.Rect(cell)
                rect_key = (round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2))
                if rect_key in seen_rects:
                    continue
                seen_rects.add(rect_key)

                row_start = _grid_index_for_position(y_positions, rect.y0)
                row_end = _grid_index_for_position(y_positions, rect.y1)
                col_start = _grid_index_for_position(x_positions, rect.x0)
                col_end = _grid_index_for_position(x_positions, rect.x1)
                font_size = _average_font_size_in_rect(font_fragments, rect)

                cells.append(
                    {
                        "cell_id": f"p{page_index + 1}_t{table_index}_r{row_start + 1}_c{col_start + 1}",
                        "row_index": row_start + 1,
                        "col_index": col_start + 1,
                        "row_span": max(row_end - row_start, 1),
                        "col_span": max(col_end - col_start, 1),
                        "rect": [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)],
                        "font_size_original": font_size,
                        "font_size_current": font_size,
                        "src_text": _extract_clipped_words_text_in_rect(
                            source_page,
                            rect,
                            textpage=source_textpage,
                        ),
                        "tgt_text": _extract_words_text_in_rect(target_words, rect),
                    }
                )

        if len(cells) < PDF_TABLE_MIN_CELLS:
            continue

        table_blocks.append(
            {
                "type": "table",
                "block_id": f"p{page_index + 1}_t{table_index}",
                "table_rect": [
                    round(float(table.bbox[0]), 2),
                    round(float(table.bbox[1]), 2),
                    round(float(table.bbox[2]), 2),
                    round(float(table.bbox[3]), 2),
                ],
                "rows_count": rows_count,
                "cols_count": cols_count,
                "cells": cells,
            }
        )

    return table_blocks


def _page_item_sort_key(item: dict[str, object]) -> tuple[float, float]:
    rect = item.get("table_rect") if item.get("type") == "table" else item.get("rect")
    if not isinstance(rect, list) or len(rect) != 4:
        return (0.0, 0.0)
    return (float(rect[1]), float(rect[0]))


def _docx_paragraph_texts(path: Path) -> list[str]:
    if not path.exists():
        return []
    document = Document(path)
    texts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                texts.extend(paragraph.text.strip() for paragraph in cell.paragraphs if paragraph.text.strip())
    return texts


def _build_pdf_pages(source_path: Path, output_path: Path) -> list[dict[str, object]]:
    source_document = fitz.open(source_path) if source_path.exists() else None
    output_document = fitz.open(output_path)
    try:
        page_count = max(source_document.page_count if source_document is not None else 0, output_document.page_count, 1)
        pages: list[dict[str, object]] = []

        for page_index in range(page_count):
            source_page = (
                source_document.load_page(page_index)
                if source_document is not None and page_index < source_document.page_count
                else None
            )
            output_page = output_document.load_page(page_index) if page_index < output_document.page_count else None
            geometry_page = output_page or source_page
            source_fragments = _extract_pdf_text_fragments(source_page) if source_page is not None else []
            target_fragments = _extract_pdf_text_fragments(output_page) if output_page is not None else []
            source_textpage = source_page.get_textpage() if source_page is not None else None
            target_textpage = output_page.get_textpage() if output_page is not None else None
            target_words = _extract_pdf_words(output_page)
            editable_fragments = target_fragments or source_fragments
            table_blocks = _extract_pdf_table_blocks(
                output_page or source_page,
                page_index=page_index,
                source_page=source_page,
                source_textpage=source_textpage,
                target_words=target_words,
                source_fragments=source_fragments,
                target_fragments=target_fragments,
            )
            table_rects = [fitz.Rect(block["table_rect"]) for block in table_blocks]
            text_blocks = _build_pdf_text_blocks(
                [fragment for fragment in editable_fragments if not _fragment_belongs_to_table(fragment, table_rects)],
                source_page=source_page,
                target_page=output_page,
                source_textpage=source_textpage,
                target_textpage=target_textpage,
            )
            page_items = sorted([*text_blocks, *table_blocks], key=_page_item_sort_key)

            page_width = round(geometry_page.rect.width, 2) if geometry_page is not None else 0.0
            page_height = round(geometry_page.rect.height, 2) if geometry_page is not None else 0.0
            blocks: list[dict[str, object]] = []

            text_block_index = 0
            for block in page_items:
                if block.get("type") == "table":
                    blocks.append(block)
                    continue

                text_block_index += 1
                blocks.append(
                    {
                        "type": "text",
                        "block_id": f"p{page_index + 1}_b{text_block_index}",
                        "rect": block["rect"],
                        "font_name": str(block.get("font_name", "")),
                        "font_size_original": float(block.get("font_size_original", 12.0) or 12.0),
                        "font_size_current": float(block.get("font_size_current", 12.0) or 12.0),
                        "src_text": str(block.get("src_text", "")),
                        "tgt_text": str(block.get("tgt_text", "")),
                    }
                )

            pages.append(
                {
                    "page_num": page_index + 1,
                    "page_width": page_width,
                    "page_height": page_height,
                    "blocks": blocks,
                }
            )

        return pages
    finally:
        output_document.close()
        if source_document is not None:
            source_document.close()


def _append_docx_preview_page(
    pages: list[dict[str, str]],
    page_index: int,
    source_parts: list[str],
    translated_parts: list[str],
) -> None:
    pages.append(
        {
            "id": f"section-{page_index}",
            "label": f"Section {page_index}",
            "source_text": "\n\n".join(part for part in source_parts if part).strip(),
            "translated_text": "\n\n".join(part for part in translated_parts if part).strip(),
        }
    )


def _build_docx_pages(source_path: Path, output_path: Path) -> list[dict[str, str]]:
    source_paragraphs = _docx_paragraph_texts(source_path)
    translated_paragraphs = _docx_paragraph_texts(output_path)
    total = max(len(source_paragraphs), len(translated_paragraphs))
    if total == 0:
        return [
            {
                "id": "section-1",
                "label": "Section 1",
                "source_text": "",
                "translated_text": "",
            }
        ]

    pages: list[dict[str, str]] = []
    source_parts: list[str] = []
    translated_parts: list[str] = []
    char_count = 0

    for index in range(total):
        source_text = source_paragraphs[index] if index < len(source_paragraphs) else ""
        translated_text = translated_paragraphs[index] if index < len(translated_paragraphs) else ""
        source_parts.append(source_text)
        translated_parts.append(translated_text)
        char_count += len(source_text) + len(translated_text)

        reached_limit = len(source_parts) >= DOCX_PREVIEW_PARAGRAPH_LIMIT or char_count >= DOCX_PREVIEW_CHAR_LIMIT
        is_last = index == total - 1
        if reached_limit or is_last:
            _append_docx_preview_page(pages, len(pages) + 1, source_parts, translated_parts)
            source_parts = []
            translated_parts = []
            char_count = 0

    return pages


def build_job_preview(job: TranslationJob, *, created_at: str | None = None) -> dict:
    if job.output_file is None:
        raise ValueError("Preview is unavailable until translation output is created")

    output_path = Path(job.output_file.storage_path)
    input_path = Path(job.input_file.storage_path)
    extension = output_path.suffix.lower()
    if extension == ".pdf":
        pages = _build_pdf_pages(input_path, output_path)
        document_kind = "pdf"
    elif extension == ".docx":
        pages = _build_docx_pages(input_path, output_path)
        document_kind = "docx"
    else:
        raise ValueError(f"Unsupported preview format: {extension}")

    now = _utcnow_iso()
    return {
        "job_id": job.id,
        "title": job.input_file.original_name,
        "output_name": job.output_file.original_name,
        "document_kind": document_kind,
        "source_language": job.source_language,
        "target_language": job.target_language,
        "created_at": created_at or now,
        "updated_at": now,
        "pages": pages,
    }


def _write_preview(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _preview_matches_schema(payload: dict, extension: str) -> bool:
    if extension == ".pdf":
        return payload.get("document_kind") == "pdf" and all(
            isinstance(page, dict)
            and "page_num" in page
            and "page_width" in page
            and "page_height" in page
            and "blocks" in page
            and all(isinstance(block, dict) and "type" in block for block in page.get("blocks", []))
            for page in payload.get("pages", [])
        )
    if extension == ".docx":
        return payload.get("document_kind") == "docx" and all(
            isinstance(page, dict)
            and "id" in page
            and "label" in page
            and "source_text" in page
            and "translated_text" in page
            for page in payload.get("pages", [])
        )
    return False


def load_or_create_preview(job: TranslationJob, *, force: bool = False) -> dict:
    if job.output_file is None:
        raise ValueError("Preview is unavailable until translation output is created")

    output_path = Path(job.output_file.storage_path)
    sidecar_path = preview_sidecar_path(job.output_file.storage_path)
    existing_preview: dict | None = None
    if sidecar_path.exists():
        try:
            with sidecar_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            existing_preview = loaded

    extension = output_path.suffix.lower()
    if not force and existing_preview is not None and _preview_matches_schema(existing_preview, extension):
        return existing_preview

    payload = build_job_preview(job, created_at=existing_preview.get("created_at") if existing_preview else None)
    _write_preview(sidecar_path, payload)
    return payload


def _update_docx_preview(preview: dict, page_updates: list[dict[str, str]]) -> dict:
    page_lookup = {page["id"]: page for page in preview["pages"]}
    for update in page_updates:
        page_id = update["id"]
        if page_id not in page_lookup:
            raise ValueError(f"Preview page '{page_id}' does not exist")
        page_lookup[page_id]["translated_text"] = update["translated_text"]

    preview["updated_at"] = _utcnow_iso()
    return preview


def _draw_pdf_block_text(page: fitz.Page, rect: fitz.Rect, text: str, font_size: float) -> None:
    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)

    normalized_text = _normalize_pdf_block_text(text)
    if not normalized_text:
        return

    font_name = _select_pdf_font(normalized_text)
    requested_size = max(float(font_size or PDF_EDITOR_MIN_FONT_SIZE), PDF_MIN_REDRAW_FONT_SIZE)
    current_size = round(requested_size, 2)
    while current_size >= PDF_MIN_REDRAW_FONT_SIZE:
        remainder = page.insert_textbox(
            rect,
            normalized_text,
            fontsize=current_size,
            fontname=font_name,
            overlay=True,
        )
        if remainder >= 0:
            return
        current_size = round(current_size - 0.5, 2)

    page.insert_textbox(
        rect,
        normalized_text,
        fontsize=PDF_MIN_REDRAW_FONT_SIZE,
        fontname=font_name,
        overlay=True,
    )


def _apply_pdf_preview_updates(job: TranslationJob, preview: dict, block_updates: list[dict[str, object]]) -> None:
    if job.output_file is None:
        raise ValueError("Translated PDF does not exist")

    output_path = Path(job.output_file.storage_path)
    if not output_path.exists():
        raise ValueError("Translated PDF does not exist")

    editable_lookup: dict[str, tuple[int, dict[str, object], str]] = {}
    for page in preview.get("pages", []):
        page_index = int(page["page_num"]) - 1
        for block in page.get("blocks", []):
            if block.get("type") == "table":
                for cell in block.get("cells", []):
                    editable_lookup[str(cell["cell_id"])] = (page_index, cell, "cell")
                continue
            editable_lookup[str(block["block_id"])] = (page_index, block, "block")

    document = fitz.open(output_path)
    with NamedTemporaryFile("wb", suffix=output_path.suffix, dir=output_path.parent, delete=False) as handle:
        temp_path = Path(handle.name)

    try:
        for update in block_updates:
            target_id = str(update.get("cell_id") or update.get("block_id") or "")
            lookup = editable_lookup.get(target_id)
            if lookup is None:
                raise ValueError(f"Preview block '{target_id}' does not exist")

            page_index, block, _ = lookup
            page = document.load_page(page_index)
            rect = fitz.Rect(block["rect"])
            _draw_pdf_block_text(
                page,
                rect,
                str(update.get("tgt_text", "")),
                float(update.get("font_size_final") or block.get("font_size_current") or block.get("font_size_original") or 12.0),
            )

        document.save(temp_path, garbage=4, deflate=True, clean=True, deflate_fonts=True)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        document.close()

    temp_path.replace(output_path)
    job.output_file.size_bytes = output_path.stat().st_size
    job.output_file.checksum = file_checksum(output_path)


def update_preview(job: TranslationJob, update_payload: dict) -> dict:
    preview = load_or_create_preview(job)
    sidecar = preview_sidecar_path(job.output_file.storage_path)

    if preview["document_kind"] == "pdf":
        if update_payload.get("status") != "validated":
            raise ValueError("PDF preview updates require status 'validated'")
        block_updates = update_payload.get("payload")
        if not isinstance(block_updates, list):
            raise ValueError("PDF preview updates require a block payload")

        _apply_pdf_preview_updates(job, preview, block_updates)
        refreshed_preview = build_job_preview(job, created_at=preview.get("created_at"))
        _write_preview(sidecar, refreshed_preview)
        return refreshed_preview

    page_updates = update_payload.get("pages")
    if not isinstance(page_updates, list):
        raise ValueError("DOCX preview updates require page content")

    updated_preview = _update_docx_preview(preview, page_updates)
    _write_preview(sidecar, updated_preview)
    return updated_preview
