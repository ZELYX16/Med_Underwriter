"""
Text matching utilities with word boundaries and negation awareness.
Prevents false positives where substrings match inside unrelated words
(e.g., 'stent' in 'consistent', 'hiv' in 'archived', 'race' in 'trace').
"""
from __future__ import annotations

import re
from typing import Any

_NEGATION_BEFORE = re.compile(
    r"\b(no|not|without|denies|denied|negative for|nil|absence of|free of|family history|"
    r"father|mother|parents?|sister|brother|quit|non[- ]?)\b[^.;\n]{0,45}$",
    re.IGNORECASE,
)


def _to_terms(term: Any) -> list[str]:
    if term is None:
        return []
    if isinstance(term, str):
        c = term.strip()
        return [c] if c else []
    if isinstance(term, (list, tuple, set)):
        result = []
        for item in term:
            c = str(item).strip()
            if c:
                result.append(c)
        return result
    c = str(term).strip()
    return [c] if c else []


def has_term(text: str | None, term: Any) -> bool:
    """True if term exists in text as complete word(s) with word boundaries."""
    if not text:
        return False
    terms = _to_terms(term)
    if not terms:
        return False
    raw = str(text)
    for clean_term in terms:
        pattern = rf"(?<!\w){re.escape(clean_term)}(?!\w)"
        if re.search(pattern, raw, re.IGNORECASE):
            return True
    return False


def has_affirmed_term(
    text: str | None,
    term: Any,
    window: int = 60,
    negations: list[str] | None = None,
) -> bool:
    """True if term appears with word boundaries and is NOT preceded by negation."""
    if not text:
        return False
    terms = _to_terms(term)
    if not terms:
        return False
    raw = str(text)
    custom_neg_regex = None
    if negations:
        escaped = [rf"{re.escape(n.strip())}" for n in negations if n.strip()]
        if escaped:
            custom_neg_regex = re.compile("|".join(escaped), re.IGNORECASE)

    for clean_term in terms:
        pattern = re.compile(rf"(?<!\w){re.escape(clean_term)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(raw):
            before = raw[max(0, match.start() - window): match.start()]
            if _NEGATION_BEFORE.search(before):
                continue
            if custom_neg_regex and custom_neg_regex.search(before):
                continue
            return True
    return False
