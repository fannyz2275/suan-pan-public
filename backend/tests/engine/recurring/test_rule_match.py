from uuid import uuid4

import pytest

from app.engine.recurring.rule_match import apply_rule_matches
from app.engine.recurring.schema import (
    RecurringRule, Frequency, Direction, Status, Source,
)


def _rule(**overrides):
    base = dict(
        user_id=uuid4(),
        keyword="Greystar Rent",
        normalized_key_pattern="greystar apts",
        amount_min=2750.00,
        amount_max=2850.00,
        amount_median=2800.00,
        frequency=Frequency.MONTHLY,
        direction=Direction.EXPENSE,
        confidence=1.0,
        status=Status.USER_CONFIRMED,
        source=Source.USER_CREATED,
    )
    base.update(overrides)
    return RecurringRule(**base)


def _txn(tid, desc, amount, d="2026-04-01"):
    return {"id": tid, "description": desc, "amount": amount, "date": d}


def test_matches_transaction_within_amount_tolerance():
    rules = [_rule()]
    txns = [_txn("t1", "POS DEBIT GREYSTAR APTS 04/01", -2820.00)]
    result = apply_rule_matches(txns, rules)
    assert result.bindings == {"t1": rules[0].id}
    assert result.unmatched == []


def test_rejects_when_normalized_key_does_not_match():
    rules = [_rule()]
    txns = [_txn("t1", "NETFLIX", -2800.00)]
    result = apply_rule_matches(txns, rules)
    assert result.bindings == {}
    assert [t["id"] for t in result.unmatched] == ["t1"]


def test_rejects_when_amount_outside_extended_tolerance():
    rules = [_rule()]  # amount_min=2750, amount_max=2850 → matching band = [2200, 3420]
    txns = [_txn("t1", "GREYSTAR APTS", -5000.00)]
    result = apply_rule_matches(txns, rules)
    assert result.bindings == {}


def test_direction_mismatch_does_not_match():
    rules = [_rule()]  # expense
    txns = [_txn("t1", "GREYSTAR APTS REFUND", +2800.00)]  # positive = income
    result = apply_rule_matches(txns, rules)
    assert result.bindings == {}


def test_rejected_rule_suppresses_matching_transaction():
    rejected = _rule(status=Status.USER_REJECTED)
    txns = [_txn("t1", "GREYSTAR APTS", -2800.00)]
    result = apply_rule_matches(txns, [rejected])
    assert result.bindings == {}
    assert result.suppressed == ["t1"]


def test_active_rules_preferred_over_rejected_in_conflict():
    active = _rule()
    rejected = _rule(status=Status.USER_REJECTED, keyword="other")
    txns = [_txn("t1", "GREYSTAR APTS", -2800.00)]
    result = apply_rule_matches(txns, [active, rejected])
    assert result.bindings == {"t1": active.id}
    assert result.suppressed == []
