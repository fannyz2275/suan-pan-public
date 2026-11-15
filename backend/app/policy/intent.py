"""5-class regex intent classifier producing the `ctx_signature` for tool
priors. The classification is intentionally coarse; this is signal-grouping
for the per-user tool-ordering aggregation, not real NLU.

Categories:
  asking_about_spending  — where money went, by category, totals
  asking_about_goals     — goal feasibility, progress, on-track
  asking_about_transfers — between accounts, transfer review
  asking_about_advice    — should I, what if, simulate, project, refi
  other                  — fallback when nothing matches

Replace with a tiny classifier model later if the regex precision plateaus
(see lock-doc Open Question OQ-4)."""
from __future__ import annotations

import re
from typing import Optional

OTHER = "other"

# Order matters — first match wins.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("asking_about_advice", re.compile(
        r"\b("
        r"should\s+i|what\s+if|recommend\w*|suggest\w*|"
        r"refi(?:nance)?\w*|simulat\w*|project\w*|forecast\w*|"
        r"buy\w*|sell\w*|prepay\w*|payoff|pay\s+off|"
        r"monte\s*carlo|"
        r"will\s+i|can\s+i\s+afford"
        r")\b",
        re.IGNORECASE,
    )),
    ("asking_about_goals", re.compile(
        r"\b("
        r"goal|target|on\s+track|feasibilit|"
        r"saving\s+for|down\s+payment|emergency\s+fund|"
        r"retirement\s+goal"
        r")\b",
        re.IGNORECASE,
    )),
    ("asking_about_transfers", re.compile(
        r"\b("
        r"transfer|venmo|zelle|cashapp|cash\s+app|"
        r"between\s+(?:my\s+)?accounts?|"
        r"internal|external|review\s+(?:my\s+)?transfers?|"
        r"mark\s+(?:as\s+)?external"
        r")\b",
        re.IGNORECASE,
    )),
    ("asking_about_spending", re.compile(
        r"\b("
        r"spend|spent|spending|expense|"
        r"budget|where\s+(?:did|does)\s+(?:my\s+)?money\s+go|"
        r"category|categor|"
        r"by\s+category|breakdown|"
        r"compare|vs\.?\b"
        r")\b",
        re.IGNORECASE,
    )),
]


def classify(text: Optional[str]) -> str:
    """Return one of the 5 ctx_signature labels for `text`. Empty / None → OTHER.
    First-match wins, ordered by lock-doc priority (advice before goals
    before transfers before spending before fallback)."""
    if not text:
        return OTHER
    for label, pattern in _PATTERNS:
        if pattern.search(text):
            return label
    return OTHER
