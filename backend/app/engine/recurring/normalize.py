from __future__ import annotations

import re
from typing import Set

_STOPWORDS = {
    "payment", "auto", "debit", "credit", "purchase", "pos",
    "ach", "xxxx", "transfer", "ref", "confirmation", "authorized",
    "pending", "online", "recurring", "bill", "fee",
}
_DATE_RE = re.compile(r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?")
_NUMERIC_RE = re.compile(r"\b\d+\b")
_PUNCT_RE = re.compile(r"[^\w\s]")
_MAX_TOKENS = 3


def normalize_description(description: str) -> str:
    """Lowercase, strip punctuation, digits, date-like tokens, stopwords; keep first 3 tokens."""
    if not description:
        return ""
    s = description.lower()
    s = _DATE_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _NUMERIC_RE.sub(" ", s)
    tokens = [t for t in s.split() if t and t not in _STOPWORDS]
    return " ".join(tokens[:_MAX_TOKENS])


def token_set(text: str) -> Set[str]:
    """Lowercase token set (no stopword filtering — callers use this for similarity)."""
    if not text:
        return set()
    s = _PUNCT_RE.sub(" ", text.lower())
    return {t for t in s.split() if t}


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
