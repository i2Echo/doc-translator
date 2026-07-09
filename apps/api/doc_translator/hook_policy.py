"""Per-rule hook policy layer for the BabelDOC internal hooks.

The convergence plan (`docs/pdf-layout-convergence-plan.md`) requires a single
switch layer so every structure rule can be toggled between ``apply`` /
``observe`` / ``off`` without editing call sites.  This module owns the only
place that reads the ``PDF_HOOK_*`` environment variables; the rules in
``babeldoc_hooks.py`` only ever ask ``HookPolicy`` what mode a rule is in.

Modes
-----
``apply``
    Run the rule and mutate the document as before.
``observe``
    Run the *plan* stage (what the rule *would* do) and record it into the
    sidecar with ``decision=observed``, but never mutate paragraph boundaries,
    composition or boxes.  This is the default for ``structure`` rules after
    M1b so ordinary body text falls back to the native BabelDOC layout path.
``off``
    Skip the rule entirely (no plan, no sidecar events).  Reserved for known
    broken rules, dead rules, or temporary fault isolation -- not a routine
    tuning knob.

Rule kinds
----------
Each rule key belongs to one kind, mirroring the plan's risk table:

* ``text_only``   -- only changes translation input/output text.
* ``style_only``  -- only changes run styles or restores a marked layout.
* ``structure``   -- splits/merges/removes/copies paragraphs, or rewrites
  ``page.pdf_paragraph``.
* ``render``      -- replaces final render units.

The per-kind default is applied when no environment variable is set for a rule.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


OBSERVE = "observe"
APPLY = "apply"
OFF = "off"
_VALID_MODES = frozenset({OBSERVE, APPLY, OFF})

TEXT_ONLY = "text_only"
STYLE_ONLY = "style_only"
STRUCTURE = "structure"
RENDER = "render"

# Per-kind default mode.  After M1b the ``structure`` cohort defaults to
# ``observe`` so ordinary body text falls back to the native BabelDOC layout
# path; the plan/apply split in ``babeldoc_hooks.py`` ensures observe mode
# records what the rule *would* do without mutating paragraph boundaries.
_KIND_DEFAULTS: dict[str, str] = {
    TEXT_ONLY: APPLY,
    STYLE_ONLY: APPLY,
    STRUCTURE: OBSERVE,
    RENDER: APPLY,
}

# Narrow, high-confidence structure repairs may opt into apply by default while
# the broader structure cohort remains observe-only.
_RULE_DEFAULTS: dict[str, str] = {
    "merge_same_line_fragment_bridge": APPLY,
    "split_wrapped_same_line_tail": APPLY,
    "remove_subsumed": APPLY,
    "collapse_overlap": APPLY,
}

# rule_key -> (rule_kind, env_var_name)
_RULES: dict[str, tuple[str, str]] = {
    # text_only cohort
    "protect_technical_tokens": (TEXT_ONLY, "PDF_HOOK_TEXT_PROTECT_TECHNICAL_TOKENS"),
    "skip_translation": (TEXT_ONLY, "PDF_HOOK_TEXT_SKIP_TRANSLATION"),
    "translate_toc_title_only": (TEXT_ONLY, "PDF_HOOK_TEXT_TRANSLATE_TOC_TITLE"),
    "restore_source_line_breaks": (TEXT_ONLY, "PDF_HOOK_TEXT_RESTORE_SOURCE_LINE_BREAKS"),
    "restore_neighbor_protected_placeholders": (TEXT_ONLY, "PDF_HOOK_TEXT_RESTORE_NEIGHBOR_PLACEHOLDERS"),
    "restore_definition_line_styles_after_translation": (TEXT_ONLY, "PDF_HOOK_TEXT_RESTORE_DEFINITION_STYLES"),
    "formula_placeholder_translation_input_override": (TEXT_ONLY, "PDF_HOOK_TEXT_FORMULA_PLACEHOLDER_OVERRIDE"),
    "composition_translation_input_override": (TEXT_ONLY, "PDF_HOOK_TEXT_COMPOSITION_INPUT_OVERRIDE"),
    "normalize_symbol_glyph_fallback_line_text": (TEXT_ONLY, "PDF_HOOK_TEXT_NORMALIZE_SYMBOL_GLYPH_FALLBACK_LINE"),
    "protect_detached_i2c_fallback_line_text": (TEXT_ONLY, "PDF_HOOK_TEXT_PROTECT_DETACHED_I2C_FALLBACK_LINE"),
    # style_only cohort
    "normalize_pdf_font_traits": (STYLE_ONLY, "PDF_HOOK_STYLE_NORMALIZE_PDF_FONT_TRAITS"),
    "restore_vertical_passthrough_layout": (STYLE_ONLY, "PDF_HOOK_STYLE_RESTORE_VERTICAL_LAYOUT"),
    "normalize_body_font_sizes": (STYLE_ONLY, "PDF_HOOK_STYLE_NORMALIZE_BODY_FONT_SIZES"),
    # structure cohort
    "normalize_fragmented": (STRUCTURE, "PDF_HOOK_STRUCTURE_NORMALIZE_FRAGMENTED"),
    "merge_same_line_fragment_bridge": (STRUCTURE, "PDF_HOOK_STRUCTURE_MERGE_SAME_LINE_FRAGMENT_BRIDGE"),
    "merge_contiguous_body_lines": (STRUCTURE, "PDF_HOOK_STRUCTURE_MERGE_CONTIGUOUS_BODY_LINES"),
    "split_wrapped_same_line_tail": (STRUCTURE, "PDF_HOOK_STRUCTURE_SPLIT_WRAPPED_SAME_LINE_TAIL"),
    "merge_same_line": (STRUCTURE, "PDF_HOOK_STRUCTURE_MERGE_SAME_LINE"),
    "remove_subsumed": (STRUCTURE, "PDF_HOOK_STRUCTURE_REMOVE_SUBSUMED"),
    "collapse_overlap": (STRUCTURE, "PDF_HOOK_STRUCTURE_COLLAPSE_OVERLAP"),
    "split_numbered_lists": (STRUCTURE, "PDF_HOOK_STRUCTURE_SPLIT_NUMBERED_LISTS"),
    "reconcile_repeated_edge": (STRUCTURE, "PDF_HOOK_STRUCTURE_RECONCILE_REPEATED_EDGE"),
    # render cohort
    "render_axis_label": (RENDER, "PDF_HOOK_RENDER_AXIS_LABEL"),
}


def as_policy(value: Any, default: str = APPLY) -> str:
    """Coerce a raw env/setting value into a valid policy mode.

    Non-empty values that are not one of the valid modes fall back to ``default``
    rather than raising, so a typo in ``.env`` cannot take the pipeline down.
    """

    if value is None:
        return default
    text = str(value).strip().lower()
    if text in _VALID_MODES:
        return text
    return default


@dataclass(frozen=True, slots=True)
class HookPolicy:
    """Resolved per-rule modes.

    ``modes`` is the authoritative map; ``_kind_defaults`` is kept only so
    ``to_summary`` can report what the *effective* default per kind was at
    construction time.
    """

    modes: dict[str, str] = field(default_factory=dict)
    _kind_defaults: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls, *, kind_defaults: dict[str, str] | None = None) -> "HookPolicy":
        """Build a policy from ``PDF_HOOK_*`` environment variables.

        ``kind_defaults`` overrides the module-level defaults (used by M1b to
        flip ``structure`` to ``observe`` without touching call sites).
        """

        resolved_defaults = dict(_KIND_DEFAULTS)
        if kind_defaults:
            resolved_defaults.update(kind_defaults)

        modes: dict[str, str] = {}
        for rule_key, (_kind, env_name) in _RULES.items():
            kind_default = resolved_defaults.get(_kind, APPLY)
            default = _RULE_DEFAULTS.get(rule_key, kind_default)
            modes[rule_key] = as_policy(os.getenv(env_name), default=default)
        return cls(modes=modes, _kind_defaults=resolved_defaults)

    @classmethod
    def with_structure_default(cls, default_mode: str) -> "HookPolicy":
        """Convenience constructor that overrides only the structure default."""

        normalized = as_policy(default_mode, default=APPLY)
        return cls.from_env(kind_defaults={STRUCTURE: normalized})

    # ------------------------------------------------------------------ #
    # Lookup
    # ------------------------------------------------------------------ #
    def kind(self, rule_key: str) -> str:
        """Return the rule kind for ``rule_key`` (raises KeyError if unknown)."""

        return _RULES[rule_key][0]

    def mode(self, rule_key: str) -> str:
        """Return the effective mode for ``rule_key`` (defaults to ``apply``)."""

        return self.modes.get(rule_key, APPLY)

    def is_apply(self, rule_key: str) -> bool:
        return self.mode(rule_key) == APPLY

    def is_observe(self, rule_key: str) -> bool:
        return self.mode(rule_key) == OBSERVE

    def is_off(self, rule_key: str) -> bool:
        return self.mode(rule_key) == OFF

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def to_summary(self) -> dict[str, Any]:
        """Serialise the policy into the sidecar for traceability."""

        by_kind: dict[str, dict[str, str]] = {}
        for rule_key, (kind, env_name) in _RULES.items():
            by_kind.setdefault(kind, {})[rule_key] = self.mode(rule_key)
        return {
            "kind_defaults": dict(self._kind_defaults),
            "modes": dict(self.modes),
            "by_kind": by_kind,
            "env_var_names": {rule_key: env for rule_key, (_kind, env) in _RULES.items()},
        }
