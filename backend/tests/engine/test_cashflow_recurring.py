from datetime import date
from uuid import uuid4

from app.engine.cashflow import project_cashflow
from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)


def _rule(freq, direction, median, **overrides):
    base = dict(
        user_id=uuid4(),
        keyword="K", normalized_key_pattern="k",
        amount_min=median * 0.9, amount_max=median * 1.1, amount_median=median,
        frequency=freq, direction=direction,
        confidence=1.0, status=Status.USER_CONFIRMED, source=Source.USER_CREATED,
    )
    base.update(overrides)
    return RecurringRule(**base)


def test_monthly_rule_adds_each_month():
    rules = [_rule(Frequency.MONTHLY, Direction.EXPENSE, 2800)]
    out = project_cashflow(
        liquid_assets=10000, monthly_income=0, monthly_expenses=0,
        months=3, start_date=date(2026, 4, 1), recurring_rules=rules,
    )
    assert out[0]["balance"] == 7200
    assert out[1]["balance"] == 4400
    assert out[2]["balance"] == 1600


def test_annual_rule_only_applies_once_per_year():
    rules = [_rule(Frequency.ANNUAL, Direction.EXPENSE, 1200)]
    out = project_cashflow(
        liquid_assets=10000, monthly_income=0, monthly_expenses=0,
        months=6, start_date=date(2026, 4, 1), recurring_rules=rules,
    )
    assert all(o["balance"] == 10000 for o in out)


def test_quarterly_rule_every_third_month():
    rules = [_rule(Frequency.QUARTERLY, Direction.INCOME, 300)]
    out = project_cashflow(
        liquid_assets=0, monthly_income=0, monthly_expenses=0,
        months=6, start_date=date(2026, 4, 1), recurring_rules=rules,
    )
    totals = sum(o["monthly_net"] + o.get("fixed_inflow", 0) - o.get("fixed_outflow", 0) for o in out)
    assert totals == 600


def test_rejected_rule_ignored():
    rules = [_rule(Frequency.MONTHLY, Direction.EXPENSE, 2800, status=Status.USER_REJECTED)]
    out = project_cashflow(
        liquid_assets=10000, monthly_income=0, monthly_expenses=0,
        months=3, start_date=date(2026, 4, 1), recurring_rules=rules,
    )
    assert all(o["balance"] == 10000 for o in out)
