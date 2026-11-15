"""Spec B Phase 2 — engine module test for app.engine.cashflow.

`project_cashflow` derives months from `date.today()` if start_date is omitted;
pass an explicit start_date to make goldens deterministic.
"""
from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.engine.cashflow import project_cashflow
from app.engine.recurring.schema import (
    Direction,
    Frequency,
    RecurringRule,
    Source,
    Status,
)


_START = date(2026, 1, 1)


def _rule(*, amount: float, freq: Frequency, direction: Direction, status=Status.AUTO_APPLIED) -> RecurringRule:
    return RecurringRule(
        user_id=uuid4(),
        keyword="rent",
        normalized_key_pattern="rent",
        amount_min=amount,
        amount_max=amount,
        amount_median=amount,
        frequency=freq,
        direction=direction,
        confidence=1.0,
        status=status,
        source=Source.HEURISTIC,
    )


def test_project_cashflow_12mo_with_rsu_golden(snapshot_json):
    rsu_events = [
        {"date": "2026-04-15", "value": 12_000.0},
        {"date": "2026-10-15", "value": 12_000.0},
    ]
    result = project_cashflow(
        liquid_assets=50_000.0,
        monthly_income=10_000.0,
        monthly_expenses=7_000.0,
        months=12,
        vesting_events=rsu_events,
        start_date=_START,
    )
    assert result == snapshot_json


def test_project_cashflow_balance_monotonic_with_positive_net():
    """When monthly_net > 0 and there are no recurring rules, balance grows each month."""
    result = project_cashflow(
        liquid_assets=10_000.0,
        monthly_income=8_000.0,
        monthly_expenses=5_000.0,
        months=6,
        start_date=_START,
    )
    balances = [r["balance"] for r in result]
    assert all(b1 < b2 for b1, b2 in zip(balances, balances[1:]))


def test_project_cashflow_with_active_recurring_rules():
    rules = [
        _rule(amount=2_000.0, freq=Frequency.MONTHLY, direction=Direction.EXPENSE),
        _rule(amount=500.0, freq=Frequency.MONTHLY, direction=Direction.INCOME),
    ]
    result = project_cashflow(
        liquid_assets=20_000.0,
        monthly_income=8_000.0,
        monthly_expenses=5_000.0,
        months=3,
        recurring_rules=rules,
        start_date=_START,
    )
    for row in result:
        assert row["fixed_outflow"] == 2_000.0
        assert row["fixed_inflow"] == 500.0


def test_project_cashflow_inactive_rules_excluded():
    """USER_REJECTED / PROPOSED rules must not influence the projection."""
    rejected = _rule(
        amount=999.0, freq=Frequency.MONTHLY, direction=Direction.EXPENSE,
        status=Status.USER_REJECTED,
    )
    proposed = _rule(
        amount=999.0, freq=Frequency.MONTHLY, direction=Direction.EXPENSE,
        status=Status.PROPOSED,
    )
    result = project_cashflow(
        liquid_assets=10_000.0,
        monthly_income=5_000.0,
        monthly_expenses=4_000.0,
        months=2,
        recurring_rules=[rejected, proposed],
        start_date=_START,
    )
    for row in result:
        assert row["fixed_outflow"] == 0.0
        assert row["fixed_inflow"] == 0.0


def test_project_cashflow_no_nan_in_output():
    """Each month's balance must be a real number (no NaN, no None)."""
    import math

    result = project_cashflow(
        liquid_assets=5_000.0,
        monthly_income=4_000.0,
        monthly_expenses=4_500.0,
        months=24,
        start_date=_START,
    )
    for row in result:
        assert isinstance(row["balance"], float)
        assert not math.isnan(row["balance"])
