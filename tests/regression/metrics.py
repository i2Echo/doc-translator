"""Metrics computation for the single-PDF regression runner.

Reads the sidecar (``doc_translator_ir.json``), the before/after structure
snapshots and the translated PDF, and produces a single ``metrics.json`` dict
covering the convergence plan's v1 indicator set (§第四阶段-2):

* paragraph_total before/after
* structure_actions_by_decision / by_role
* structure_guard_decisions
* multiline_prose_rewrites (rejected multi_line_blocks + observed multiline_body_block)
* font_size_normalize_hits
* page_text_coverage (per page)
* overflow_paragraphs (bbox proxy, v1)
* hook_policy summary

The metrics are deliberately statistical, not visual: they are stable enough to
gate a PR on and small enough to diff by hand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _count_actions_by_decision(applied_events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Return ``{action: {applied, observed, rejected, skipped}}``."""

    by_decision: dict[str, dict[str, int]] = {}
    for event in applied_events or []:
        action = str(event.get("action") or "unknown")
        decision = str(event.get("decision") or "unknown")
        bucket = by_decision.setdefault(action, {"applied": 0, "observed": 0, "rejected": 0, "skipped": 0, "unknown": 0})
        bucket[decision] = bucket.get(decision, 0) + 1
    return by_decision


def _event_role_counts(event: dict[str, Any]) -> dict[str, int]:
    raw_counts = event.get("role_counts")
    if isinstance(raw_counts, dict):
        counts: dict[str, int] = {}
        for role, value in raw_counts.items():
            if isinstance(value, (int, float)):
                counts[str(role)] = counts.get(str(role), 0) + int(value)
        if counts:
            return counts

    counts: dict[str, int] = {}
    role = event.get("role")
    if role:
        counts[str(role)] = counts.get(str(role), 0) + 1
    for sample in event.get("samples") or []:
        for key in ("role", "left_role", "right_role"):
            sample_role = sample.get(key)
            if not sample_role:
                continue
            counts[str(sample_role)] = counts.get(str(sample_role), 0) + 1
    return counts


def _count_structure_actions_by_role(applied_events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Return ``{action: {role: count}}`` for structure-kind actions only."""

    by_role: dict[str, dict[str, int]] = {}
    for event in applied_events or []:
        rule_kind = str(event.get("rule_kind") or "")
        if rule_kind != "structure":
            continue
        action = str(event.get("action") or "unknown")
        by_role.setdefault(action, {})
        for role, count in _event_role_counts(event).items():
            by_role[action][role] = by_role[action].get(role, 0) + count
    return by_role


def _count_structure_guard_decisions(applied_events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_reason: dict[str, dict[str, int]] = {}
    for event in applied_events or []:
        if str(event.get("rule_kind") or "") != "structure":
            continue
        for sample in event.get("samples") or []:
            decision = str(sample.get("guard_decision") or "")
            reason = str(sample.get("guard_reason") or "")
            if not decision or not reason:
                continue
            bucket = by_reason.setdefault(reason, {"allowed": 0, "rejected": 0})
            bucket[decision] = bucket.get(decision, 0) + 1
    return by_reason


def _multiline_prose_rewrites(applied_events: list[dict[str, Any]]) -> dict[str, int]:
    """Count structure events whose reason flags a multiline body block.

    Two sources: ``merge_same_line`` rejects with ``reason=multi_line_blocks``,
    and ``normalize_fragmented`` observed plans whose items carry
    ``reason=multiline_body_block``.  Both mean a real prose block was left
    alone, which is the desired止血 outcome.
    """

    counts = {"rejected_multi_line_blocks": 0, "observed_multiline_body_block": 0}
    for event in applied_events or []:
        action = str(event.get("action") or "")
        decision = str(event.get("decision") or "")
        if action == "reject_same_line_fragment_merge" and decision == "rejected":
            for sample in event.get("samples") or []:
                if str(sample.get("reason") or "") == "multi_line_blocks":
                    counts["rejected_multi_line_blocks"] += 1
        if action == "split_multiline_paragraphs_before_translation" and decision == "observed":
            for sample in event.get("samples") or []:
                if str(sample.get("reason") or "") == "multiline_body_block":
                    counts["observed_multiline_body_block"] += 1
    return counts


def _font_size_normalize_hits(applied_events: list[dict[str, Any]]) -> int:
    for event in applied_events or []:
        if str(event.get("action") or "") == "normalize_body_font_sizes_before_typesetting":
            return int(event.get("runs") or 0)
    return 0


def _structure_action_role_counts(applied_events: list[dict[str, Any]]) -> dict[str, int]:
    """Count structure actions grouped by decision for body-role paragraphs.

    The convergence plan's first-stage acceptance bar is "structure actions on
    ordinary body text with decision=applied approach 0".  This rolls up that
    single number across every structure rule.
    """

    totals: dict[str, int] = {"applied": 0, "observed": 0, "rejected": 0, "skipped": 0}
    for event in applied_events or []:
        if str(event.get("rule_kind") or "") != "structure":
            continue
        decision = str(event.get("decision") or "unknown")
        body_hits = _ordinary_body_structure_hits(event)
        if body_hits:
            totals[decision] = totals.get(decision, 0) + body_hits
    return totals


def _ordinary_body_structure_hits(event: dict[str, Any]) -> int:
    """Count body hits that still represent ordinary body-structure risk."""

    body_hits = _event_role_counts(event).get("body", 0)
    if body_hits <= 0:
        return 0
    if str(event.get("decision") or "") != "applied":
        return body_hits
    safe_hits = 0
    for sample in event.get("samples") or []:
        if str(sample.get("guard_reason") or "") != "mixed_region_same_line_text_continuation":
            continue
        if str(sample.get("left_role") or "") == "body":
            safe_hits += 1
        if str(sample.get("right_role") or "") == "body":
            safe_hits += 1
    return max(body_hits - safe_hits, 0)


def _page_text_coverage(pdf_path: Path) -> dict[str, Any]:
    """Per-page text bbox coverage vs page area, via PyMuPDF."""

    try:
        import fitz
    except ImportError:
        return {"available": False, "reason": "PyMuPDF not installed"}
    if not pdf_path.exists():
        return {"available": False, "reason": "output pdf missing"}
    pages: list[dict[str, Any]] = []
    with fitz.open(str(pdf_path)) as doc:
        for page_index, page in enumerate(doc):
            page_rect = page.rect
            page_area = max(page_rect.width * page_rect.height, 1.0)
            text_area = 0.0
            for block in page.get_text("blocks") or []:
                x0, y0, x1, y1 = block[:4]
                text_area += max(0.0, (x1 - x0)) * max(0.0, (y1 - y0))
            pages.append(
                {
                    "page": page_index + 1,
                    "coverage": round(text_area / page_area, 4),
                }
            )
    return {"available": True, "pages": pages}


def _overflow_paragraphs(pdf_path: Path, margin_ratio: float = 0.015) -> dict[str, Any]:
    """Proxy overflow metric: count blocks whose bbox exceeds the page mediabox.

    This is a v1 stand-in for BabelDOC ``layout_status=overflow``.  A block is
    counted as overflow when any edge crosses past ``margin_ratio`` of the page
    dimension beyond the mediabox.  The method is tagged in the output so future
    versions can swap in the real IR field without confusing baselines.
    """

    try:
        import fitz
    except ImportError:
        return {"available": False, "reason": "PyMuPDF not installed", "method": "bbox_proxy_v1"}
    if not pdf_path.exists():
        return {"available": False, "reason": "output pdf missing", "method": "bbox_proxy_v1"}
    per_page: list[dict[str, Any]] = []
    total = 0
    with fitz.open(str(pdf_path)) as doc:
        for page_index, page in enumerate(doc):
            page_rect = page.rect
            dx = page_rect.width * margin_ratio
            dy = page_rect.height * margin_ratio
            # PyMuPDF Rect uses x0/y0/x1/y1 (not x/x2/y2).
            px0, py0, px1, py1 = page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1
            page_overflow = 0
            for block in page.get_text("blocks") or []:
                x0, y0, x1, y1 = block[:4]
                if (
                    x0 < px0 - dx
                    or y0 < py0 - dy
                    or x1 > px1 + dx
                    or y1 > py1 + dy
                ):
                    page_overflow += 1
            per_page.append({"page": page_index + 1, "overflow_blocks": page_overflow})
            total += page_overflow
    return {"available": True, "method": "bbox_proxy_v1", "total": total, "per_page": per_page}


def compute_metrics(
    *,
    output_dir: Path,
    mono_pdf: Path,
    input_name: str,
) -> dict[str, Any]:
    """Build the metrics dict for a single translated sample.

    ``output_dir`` is the run directory containing the sidecar + snapshots.
    """

    sidecar = _safe_load_json(output_dir / "doc_translator_ir.json") or {}
    before = _safe_load_json(output_dir / "structure_before.json") or {}
    after = _safe_load_json(output_dir / "structure_after.json") or {}
    applied_events = sidecar.get("applied_events") or []

    return {
        "schema_version": 1,
        "input": input_name,
        "paragraph_total_before": before.get("paragraph_total"),
        "paragraph_total_after": after.get("paragraph_total"),
        "structure_actions_by_decision": _count_actions_by_decision(applied_events),
        "structure_actions_by_role": _count_structure_actions_by_role(applied_events),
        "structure_guard_decisions": _count_structure_guard_decisions(applied_events),
        "body_role_structure_decisions": _structure_action_role_counts(applied_events),
        "multiline_prose_rewrites": _multiline_prose_rewrites(applied_events),
        "font_size_normalize_hits": _font_size_normalize_hits(applied_events),
        "page_text_coverage": _page_text_coverage(mono_pdf),
        "overflow_paragraphs": _overflow_paragraphs(mono_pdf),
        "hook_policy": sidecar.get("hook_policy") or {},
        "role_counts": sidecar.get("counts") or {},
    }


# ---------------------------------------------------------------------- #
# Baseline diff / hard gates
# ---------------------------------------------------------------------- #

# Metrics whose *increase* is a regression.  Each entry maps a dotted path in
# the metrics dict to a human-readable gate name.  A regression is any path
# whose value went up relative to the baseline (improvements are not gated).
_REGRESSION_PATHS: tuple[tuple[str, str], ...] = (
    ("body_role_structure_decisions.applied", "body_text_structure_applied"),
    ("overflow_paragraphs.total", "overflow_total"),
    ("structure_guard_decisions.cross_column.allowed", "cross_column_allowed"),
    ("structure_guard_decisions.unknown_region.allowed", "unknown_region_allowed"),
    ("structure_guard_decisions.non_body_region.allowed", "non_body_region_allowed"),
    ("structure_guard_decisions.ordinary_body_split.allowed", "ordinary_body_split_allowed"),
    ("structure_guard_decisions.multiline_body_block.allowed", "multiline_body_split_allowed"),
)


def _dotted_get(data: dict[str, Any], path: str) -> int:
    cursor: Any = data
    for part in path.split("."):
        if not isinstance(cursor, dict):
            return 0
        cursor = cursor.get(part)
    if isinstance(cursor, (int, float)):
        return int(cursor)
    return 0


def diff_metrics(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Compare ``current`` against ``baseline`` and flag regressions.

    Only worsening directions fail (plan §第四阶段-4): ``applied`` body-text
    structure actions increasing, overflow increasing.  Improvements and
    unchanged values are reported as diffs but do not fail.
    """

    regressions: list[dict[str, Any]] = []
    diffs: list[dict[str, Any]] = []
    for path, gate_name in _REGRESSION_PATHS:
        before = _dotted_get(baseline, path)
        after = _dotted_get(current, path)
        delta = after - before
        entry = {"gate": gate_name, "path": path, "before": before, "after": after, "delta": delta}
        diffs.append(entry)
        if delta > 0:
            regressions.append(entry)
    return {"regressions": regressions, "diffs": diffs, "failed": bool(regressions)}
