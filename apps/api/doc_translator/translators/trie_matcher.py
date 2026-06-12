from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class TerminologyMatch:
    source: str
    target: str


def _config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "glossary_domains.json"


@lru_cache(maxsize=1)
def load_glossary_terms(domain: str = "pcb_semiconductor") -> dict[str, str]:
    payload = json.loads(_config_path().read_text(encoding="utf-8"))
    terms = payload.get(domain, {})
    return {str(source): str(target) for source, target in terms.items()}


class TerminologyMatcher:
    def __init__(self, terms: dict[str, str] | None = None) -> None:
        self.terms = dict(terms or load_glossary_terms())
        self._folded_to_source = {source.casefold(): source for source in self.terms}
        try:
            import marisa_trie
        except ImportError:
            self._trie = None
        else:
            self._trie = marisa_trie.Trie(self._folded_to_source)

    def scan(self, texts: Iterable[str]) -> tuple[TerminologyMatch, ...]:
        matches: dict[str, TerminologyMatch] = {}
        for text in texts:
            folded = str(text or "").casefold()
            if not folded:
                continue
            if self._trie is None:
                sources = (
                    source
                    for folded_source, source in self._folded_to_source.items()
                    if folded_source in folded
                )
            else:
                found: set[str] = set()
                for index in range(len(folded)):
                    found.update(self._trie.prefixes(folded[index:]))
                sources = (self._folded_to_source[folded_source] for folded_source in found)
            for source in sources:
                matches[source.casefold()] = TerminologyMatch(source=source, target=self.terms[source])
        return tuple(matches[key] for key in sorted(matches))


@lru_cache(maxsize=1)
def default_terminology_matcher() -> TerminologyMatcher:
    return TerminologyMatcher()
