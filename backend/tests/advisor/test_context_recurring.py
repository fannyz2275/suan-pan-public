from uuid import uuid4

from app.advisor.context import compute_recurring_totals
from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)


def _rule(direction, median, status=None):
    return RecurringRule(
        user_id=uuid4(), keyword="K", normalized_key_pattern="k",
        amount_min=median * 0.9, amount_max=median * 1.1, amount_median=median,
        frequency=Frequency.MONTHLY, direction=direction,
        confidence=1.0, status=status or Status.USER_CONFIRMED, source=Source.USER_CREATED,
    )


def test_totals_sum_active_rules():
    rules = [
        _rule(Direction.EXPENSE, 2800),
        _rule(Direction.EXPENSE, 120),
        _rule(Direction.INCOME, 5000),
    ]
    totals = compute_recurring_totals(rules)
    assert totals["fixed_monthly_outflow"] == 2920.0
    assert totals["fixed_monthly_inflow"] == 5000.0


def test_totals_ignore_rejected_and_proposed_rules():
    rules = [
        _rule(Direction.EXPENSE, 2800, status=Status.USER_REJECTED),
        _rule(Direction.EXPENSE, 120, status=Status.PROPOSED),
        _rule(Direction.EXPENSE, 50, status=Status.AUTO_APPLIED),  # counts
    ]
    totals = compute_recurring_totals(rules)
    assert totals["fixed_monthly_outflow"] == 50.0
    assert totals["fixed_monthly_inflow"] == 0.0


def test_totals_convert_non_monthly_frequencies():
    # Annual 1200 → 100/mo; weekly 10 → 10 * 52 / 12 ≈ 43.33
    rules = [
        RecurringRule(
            user_id=uuid4(), keyword="A", normalized_key_pattern="a",
            amount_min=1200 * 0.9, amount_max=1200 * 1.1, amount_median=1200,
            frequency=Frequency.ANNUAL, direction=Direction.EXPENSE,
            confidence=1.0, status=Status.USER_CONFIRMED, source=Source.USER_CREATED,
        ),
        RecurringRule(
            user_id=uuid4(), keyword="B", normalized_key_pattern="b",
            amount_min=10 * 0.9, amount_max=10 * 1.1, amount_median=10,
            frequency=Frequency.WEEKLY, direction=Direction.EXPENSE,
            confidence=1.0, status=Status.USER_CONFIRMED, source=Source.USER_CREATED,
        ),
    ]
    totals = compute_recurring_totals(rules)
    assert totals["fixed_monthly_outflow"] == round(100 + 10 * 52 / 12, 2)


# build_financial_context-prose tests deleted with the legacy builder.
# Equivalent rendering coverage now lives in tests/advisor/test_context.py
# under build_live_state_block / build_financial_context.
