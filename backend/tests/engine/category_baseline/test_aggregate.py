import uuid

from app.engine.category_baseline.aggregate import aggregate_by_category_month
from app.engine.recurring.schema import (
    Direction,
    Frequency,
    RecurringRule,
    Source,
    Status,
)


def _txn(id, date, amount, category="shopping", description="random merchant"):
    return {
        "id": id,
        "date": date,
        "amount": amount,
        "category": category,
        "description": description,
    }


def test_groups_by_category_and_month():
    txns = [
        _txn("1", "2026-01-15", -100, "shopping"),
        _txn("2", "2026-01-22", -50, "shopping"),
        _txn("3", "2026-02-03", -120, "shopping"),
        _txn("4", "2026-01-10", -80, "food"),
    ]

    result = aggregate_by_category_month(txns)

    assert result["shopping"] == [("2026-01", 150.0), ("2026-02", 120.0)]
    assert result["food"] == [("2026-01", 80.0)]


def test_excludes_income_and_transfer_categories():
    txns = [
        _txn("1", "2026-01-15", 5000, "income"),
        _txn("2", "2026-01-15", -200, "transfer"),
        _txn("3", "2026-01-15", -50, "food"),
    ]

    result = aggregate_by_category_month(txns)

    assert "income" not in result
    assert "transfer" not in result
    assert result["food"] == [("2026-01", 50.0)]


def test_excludes_positive_amounts():
    """Refunds/credits in expense categories shouldn't skew the baseline."""
    txns = [
        _txn("1", "2026-01-15", -100, "shopping"),
        _txn("2", "2026-01-22", 30, "shopping"),  # refund
    ]

    result = aggregate_by_category_month(txns)

    assert result["shopping"] == [("2026-01", 100.0)]


def test_excludes_recurring_rule_matched_transactions():
    """Rent shouldn't be double-counted: once in housing, once as recurring."""
    rule = RecurringRule(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        keyword="property mgmt rent",
        normalized_key_pattern="property mgmt rent",
        direction=Direction.EXPENSE,
        frequency=Frequency.MONTHLY,
        amount_min=1900,
        amount_median=2000,
        amount_max=2100,
        last_seen_date="2026-01-01",
        confidence=0.9,
        status=Status.USER_CONFIRMED,
        source=Source.HEURISTIC,
    )
    txns = [
        _txn("1", "2026-01-01", -2000, "housing", "PROPERTY MGMT RENT JAN"),
        _txn("2", "2026-02-01", -2000, "housing", "PROPERTY MGMT RENT FEB"),
        _txn("3", "2026-01-15", -50, "food", "trader joes"),
    ]

    result = aggregate_by_category_month(txns, recurring_rules=[rule])

    assert "housing" not in result
    assert result["food"] == [("2026-01", 50.0)]


def test_excluded_transaction_ids_dropped():
    txns = [
        _txn("1", "2026-01-15", -100, "shopping"),
        _txn("2", "2026-01-22", -50, "shopping"),
    ]

    result = aggregate_by_category_month(txns, excluded_transaction_ids={"1"})

    assert result["shopping"] == [("2026-01", 50.0)]


def test_skips_malformed_dates():
    txns = [
        _txn("1", "not-a-date", -100, "shopping"),
        _txn("2", "2026-01-15", -50, "shopping"),
    ]

    result = aggregate_by_category_month(txns)

    assert result["shopping"] == [("2026-01", 50.0)]
