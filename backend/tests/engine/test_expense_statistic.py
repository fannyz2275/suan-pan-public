from datetime import date
from app.engine.expense_statistic import compute_expense_statistic


def _txn(d, amount, status=None):
    return {"date": d, "amount": amount, "transfer_status": status}


def test_empty_transactions_returns_insufficient_data():
    out = compute_expense_statistic([], window_days=90, today=date(2026, 4, 27))
    assert out == {"value": None, "source": "insufficient_data",
                   "sample_size": 0, "window_days": 90}


def test_only_income_returns_insufficient_data():
    txns = [_txn("2026-04-15", 5000), _txn("2026-03-15", 5000)]
    out = compute_expense_statistic(txns, today=date(2026, 4, 27))
    assert out["source"] == "insufficient_data"
    assert out["value"] is None


def test_only_transfers_returns_insufficient_data():
    txns = [
        _txn("2026-04-15", -1000, "auto_paired"),
        _txn("2026-03-15", -1000, "user_confirmed_internal"),
        _txn("2026-02-15", -1000, "external"),
    ]
    out = compute_expense_statistic(txns, today=date(2026, 4, 27))
    assert out["source"] == "insufficient_data"


def test_window_too_short_returns_insufficient_data():
    txns = [_txn("2026-04-22", -100)]
    out = compute_expense_statistic(txns, today=date(2026, 4, 27))
    assert out["source"] == "insufficient_data"


def test_90_days_of_expenses_returns_computed_average():
    txns = [
        _txn("2026-02-01", -1500),
        _txn("2026-03-01", -1500),
        _txn("2026-04-01", -1500),
    ]
    out = compute_expense_statistic(txns, window_days=90, today=date(2026, 4, 27))
    assert out["source"] == "computed"
    assert out["sample_size"] == 3
    assert out["value"] == 1500.0


def test_excludes_transfers_from_average():
    txns = [
        _txn("2026-02-01", -1500),
        _txn("2026-03-01", -500, "auto_paired"),
        _txn("2026-04-01", -1500),
    ]
    out = compute_expense_statistic(txns, window_days=90, today=date(2026, 4, 27))
    assert out["sample_size"] == 2
    assert out["value"] == 1000.0


def test_ignores_transactions_outside_window():
    txns = [
        _txn("2025-09-01", -1500),
        _txn("2026-02-01", -1500),
        _txn("2026-04-01", -1500),
    ]
    out = compute_expense_statistic(txns, window_days=90, today=date(2026, 4, 27))
    assert out["sample_size"] == 2
