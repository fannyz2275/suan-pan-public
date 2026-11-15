from datetime import date, timedelta
from uuid import uuid4

from app.engine.recurring.detector import detect_recurring_rules
from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)


def _monthly_txns(tid_prefix, desc, amount, start, n=12):
    return [
        {
            "id": f"{tid_prefix}{i}", "description": desc, "amount": amount,
            "date": (start + timedelta(days=30 * i)).isoformat(),
            "transfer_status": None,
        }
        for i in range(n)
    ]


def test_full_flow_rent_salary_utility():
    user_id = uuid4()
    start = date(2025, 5, 1)
    txns = []
    txns += _monthly_txns("rent", "POS DEBIT GREYSTAR APTS", -2800, start, n=12)
    txns += _monthly_txns("sal1", "ACME PAYROLL DEPOSIT", 5000, start, n=12)
    for i in range(11):
        txns.append({
            "id": f"util{i}", "description": "PG E ELECTRIC",
            "amount": -(50 + 15 * i) if i % 3 == 0 else -90,
            "date": (start + timedelta(days=30 * i)).isoformat(),
            "transfer_status": None,
        })

    rules = detect_recurring_rules(
        transactions=txns, active_rules=[], user_id=user_id, today=date(2026, 5, 1),
    )
    kinds = {(r.direction, r.frequency): r for r in rules}
    assert (Direction.EXPENSE, Frequency.MONTHLY) in kinds  # rent or utility
    rent = next(r for r in rules if "GREYSTAR" in r.keyword.upper())
    assert rent.status == Status.AUTO_APPLIED
    salary = next(r for r in rules if r.direction == Direction.INCOME)
    assert salary.status == Status.AUTO_APPLIED


def test_feedback_loop_prior_confirmation_boosts_future_run():
    user_id = uuid4()
    start = date(2026, 1, 15)
    txns = [
        {"id": f"g{i}", "description": "CRUNCH GYM", "amount": -15.99,
         "date": (start + timedelta(days=30 * i)).isoformat(), "transfer_status": None}
        for i in range(3)
    ]
    first = detect_recurring_rules(transactions=txns, active_rules=[], user_id=user_id, today=date(2026, 4, 1))
    assert first, "expected at least one rule"
    gym = next(r for r in first if "CRUNCH" in r.keyword.upper())
    confirmed = gym.model_copy(update={"status": Status.USER_CONFIRMED})

    new_txn = {"id": "g_new", "description": "CRUNCH GYM", "amount": -15.99,
               "date": "2026-05-15", "transfer_status": None}
    second = detect_recurring_rules(
        transactions=txns + [new_txn], active_rules=[confirmed],
        user_id=user_id, today=date(2026, 6, 1),
    )
    matched = [r for r in second if r.id == confirmed.id]
    assert len(matched) == 1
    assert matched[0].occurrences_observed >= confirmed.occurrences_observed + 1
