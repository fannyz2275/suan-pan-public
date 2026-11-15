import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from app.engine.recurring.schema import Frequency, RecurringRule


def parse_advisor_actions(response_text: str) -> Dict[str, Any]:
    """Extracts structured <actions> block from the advisor's response if present."""
    match = re.search(r"<actions>(.*?)</actions>", response_text, re.DOTALL)
    if not match:
        return {"new_goals": []}
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return {"new_goals": []}


def strip_actions_block(response_text: str) -> str:
    """Removes the <actions> block from response text for display."""
    return re.sub(r"\s*<actions>.*?</actions>", "", response_text, flags=re.DOTALL).strip()


@dataclass
class RecurringReviewAction:
    kind: Literal["confirm", "reject", "edit", "create", "noop"]
    updates: dict = None  # type: ignore[assignment]
    rule_id: Optional[Any] = None

    def __post_init__(self):
        if self.updates is None:
            self.updates = {}


_MONEY_RE = re.compile(r"(?<!\d)\$?([0-9][0-9,]*(?:\.\d{1,2})?)(?!\d)")
_FREQ_MAP = {
    # Multi-word / hyphenated entries must come first so that longer keys are
    # matched before single-word substrings (e.g. "semi-monthly" before "monthly").
    "semi-monthly": Frequency.SEMI_MONTHLY,
    "semi monthly": Frequency.SEMI_MONTHLY,
    "semimonthly": Frequency.SEMI_MONTHLY,
    "semi-annual": Frequency.SEMI_ANNUAL,
    "semi annual": Frequency.SEMI_ANNUAL,
    "semiannual": Frequency.SEMI_ANNUAL,
    "bi-weekly": Frequency.BIWEEKLY,
    "biweekly": Frequency.BIWEEKLY,
    "weekly": Frequency.WEEKLY,
    "monthly": Frequency.MONTHLY,
    "quarterly": Frequency.QUARTERLY,
    "annual": Frequency.ANNUAL,
    "yearly": Frequency.ANNUAL,
}

_KEYWORD_STOPWORDS = {
    "Add", "My", "The", "A", "An", "I", "Edit", "Confirm", "Yes", "No", "Please",
    "Mark", "Set", "Record", "New", "This",
}


def _extract_amount(text: str) -> Optional[float]:
    m = _MONEY_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def _extract_frequency(text: str) -> Optional[str]:
    lowered = text.lower()
    for k, v in _FREQ_MAP.items():
        if k in lowered:
            return v.value
    return None


def _extract_keyword(text: str) -> str:
    # First capitalized token that isn't a common action verb/stopword.
    for m in re.finditer(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\b", text):
        candidate = m.group(1)
        if candidate.split()[0] in _KEYWORD_STOPWORDS:
            continue
        return candidate
    tokens = text.split()
    return tokens[1] if len(tokens) > 1 else (tokens[0] if tokens else "New")


def parse_recurring_review_reply(
    text: str, rule: Optional[RecurringRule]
) -> RecurringReviewAction:
    lowered = text.strip().lower()

    if rule is not None:
        if lowered in {"yes", "y", "yeah", "yep", "confirm"}:
            return RecurringReviewAction(kind="confirm")
        if lowered.startswith("no") or lowered == "n" or lowered == "reject":
            return RecurringReviewAction(kind="reject")
        if lowered.startswith("edit"):
            updates: dict = {}
            amt = _extract_amount(text)
            if amt is not None:
                updates["amount_median"] = amt
            freq = _extract_frequency(text)
            if freq is not None:
                updates["frequency"] = freq
            return RecurringReviewAction(kind="edit", updates=updates)

    # Free-form add.
    if "add" in lowered or "recurring" in lowered or "subscription" in lowered:
        return RecurringReviewAction(
            kind="create",
            updates={
                "keyword": _extract_keyword(text),
                "amount_median": _extract_amount(text),
                "frequency": _extract_frequency(text),
            },
        )

    return RecurringReviewAction(kind="noop")
