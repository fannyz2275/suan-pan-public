"""Spec B §14.2 — meta-tests for hypothesis strategies in `strategies.py`.

These verify that strategies generate well-formed dicts, never produce NaN, and
match the schema each invariant test expects.
"""
from __future__ import annotations

import math

from hypothesis import given, settings

from .strategies import (
    ATTRIBUTION_TXN_TYPES,
    attribution_transaction_strategy,
    attribution_transactions,
    period_value,
)


@given(txn=attribution_transaction_strategy())
@settings(max_examples=50)
def test_attribution_transaction_strategy_generates_valid_dict(txn):
    assert set(txn.keys()) == {"type", "amount", "date", "ticker"}
    assert txn["type"] in ATTRIBUTION_TXN_TYPES


@given(txn=attribution_transaction_strategy())
@settings(max_examples=50)
def test_attribution_transaction_strategy_no_nan(txn):
    assert isinstance(txn["amount"], float)
    assert not math.isnan(txn["amount"])
    assert not math.isinf(txn["amount"])


@given(txns=attribution_transactions)
@settings(max_examples=20)
def test_attribution_transactions_list_is_bounded(txns):
    assert 0 <= len(txns) <= 20
    for t in txns:
        assert -100_000 <= t["amount"] <= 100_000


@given(value=period_value)
@settings(max_examples=50)
def test_period_value_strategy_non_negative_and_finite(value):
    assert value >= 0
    assert not math.isnan(value)
    assert not math.isinf(value)
