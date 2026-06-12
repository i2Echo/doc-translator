from __future__ import annotations

from typing import Iterable

from doc_translator.translators.trie_matcher import TerminologyMatch


def build_terminology_instruction(matches: Iterable[TerminologyMatch]) -> str:
    rows = [f"- {match.source} => {match.target}" for match in matches]
    if not rows:
        return ""
    return (
        "Terminology compliance is mandatory. Preserve every locked term exactly as specified; "
        "do not omit, paraphrase, or translate these terms differently:\n"
        + "\n".join(rows)
    )
