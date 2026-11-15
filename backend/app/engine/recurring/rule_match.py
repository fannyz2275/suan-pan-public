from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List
from uuid import UUID

from app.engine.recurring.normalize import normalize_description, token_set, jaccard
from app.engine.recurring.schema import Direction, RecurringRule, Status

_MATCH_AMOUNT_LO = 0.8  # spec §4 step 3: amount_min × 0.8
_MATCH_AMOUNT_HI = 1.2  # spec §4 step 3: amount_max × 1.2
_PATTERN_JACCARD_THRESHOLD = 0.6


@dataclass
class RuleMatchResult:
    bindings: Dict[str, UUID] = field(default_factory=dict)       # txn_id → rule_id
    unmatched: List[dict] = field(default_factory=list)           # passes through to clustering
    suppressed: List[str] = field(default_factory=list)           # txn_ids hidden by user_rejected rules


def _direction_of(amount: float) -> Direction:
    return Direction.INCOME if amount > 0 else Direction.EXPENSE


def _pattern_matches(rule_pattern: str, txn_desc: str) -> bool:
    rule_tokens = token_set(rule_pattern)
    txn_tokens = token_set(normalize_description(txn_desc))
    if not rule_tokens:
        return False
    return jaccard(rule_tokens, txn_tokens) >= _PATTERN_JACCARD_THRESHOLD


def _amount_in_band(rule: RecurringRule, amount: float) -> bool:
    abs_amt = abs(amount)
    lo = rule.amount_min * _MATCH_AMOUNT_LO
    hi = rule.amount_max * _MATCH_AMOUNT_HI
    return lo <= abs_amt <= hi


def apply_rule_matches(
    transactions: Iterable[dict],
    rules: Iterable[RecurringRule],
) -> RuleMatchResult:
    """First pass: bind transactions to active rules; suppress those matching rejected rules.

    Preference order in conflict: user_confirmed > auto_applied > (rejected suppresses).
    """
    active = [r for r in rules if r.status in (Status.USER_CONFIRMED, Status.AUTO_APPLIED)]
    rejected = [r for r in rules if r.status == Status.USER_REJECTED]

    result = RuleMatchResult()
    for t in transactions:
        amount = float(t["amount"])
        direction = _direction_of(amount)
        desc = t.get("description", "")

        # Active match wins.
        winner = None
        for r in active:
            if r.direction != direction:
                continue
            if _pattern_matches(r.normalized_key_pattern, desc) and _amount_in_band(r, amount):
                if winner is None or r.status == Status.USER_CONFIRMED:
                    winner = r
        if winner is not None:
            result.bindings[t["id"]] = winner.id
            continue

        # Otherwise, check rejection suppression.
        suppressed = False
        for r in rejected:
            if r.direction != direction:
                continue
            if _pattern_matches(r.normalized_key_pattern, desc) and _amount_in_band(r, amount):
                suppressed = True
                break
        if suppressed:
            result.suppressed.append(t["id"])
        else:
            result.unmatched.append(t)

    return result
