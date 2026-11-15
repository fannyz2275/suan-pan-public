from datetime import date
from unittest.mock import patch

from app.engine.cashflow import compute_historical_cashflow


def _txn(d: str, amount: float):
    return {"date": d, "amount": amount}


def test_empty_transactions_yields_flat_series_at_ending_balance():
    with patch("app.engine.cashflow.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 27)
        mock_date.fromisoformat = date.fromisoformat
        result = compute_historical_cashflow(transactions=[], ending_balance=10000, months=3)
    assert len(result) == 3
    assert all(r["net"] == 0 for r in result)
    assert all(r["balance"] == 10000 for r in result)


def test_returns_oldest_first_with_correct_months():
    with patch("app.engine.cashflow.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 27)
        mock_date.fromisoformat = date.fromisoformat
        result = compute_historical_cashflow(transactions=[], ending_balance=5000, months=3)
    months = [r["month"] for r in result]
    assert months == ["2026-01", "2026-02", "2026-03"]


def test_aggregates_inflows_and_outflows_signed():
    with patch("app.engine.cashflow.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 27)
        mock_date.fromisoformat = date.fromisoformat
        txns = [
            _txn("2026-03-15", 5000),
            _txn("2026-03-20", -300),
            _txn("2026-03-22", -200),
        ]
        result = compute_historical_cashflow(transactions=txns, ending_balance=10000, months=3)
    march = next(r for r in result if r["month"] == "2026-03")
    assert march["net"] == 4500


def test_walks_backward_from_ending_balance():
    with patch("app.engine.cashflow.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 27)
        mock_date.fromisoformat = date.fromisoformat
        txns = [_txn("2026-03-15", 5000)]
        result = compute_historical_cashflow(transactions=txns, ending_balance=10000, months=3)
    by_month = {r["month"]: r for r in result}
    assert by_month["2026-03"]["balance"] == 10000
    assert by_month["2026-02"]["balance"] == 5000
    assert by_month["2026-01"]["balance"] == 5000


def test_ignores_transactions_in_current_or_future_months():
    with patch("app.engine.cashflow.date") as mock_date:
        mock_date.today.return_value = date(2026, 4, 27)
        mock_date.fromisoformat = date.fromisoformat
        txns = [
            _txn("2026-04-15", 9999),
            _txn("2026-05-01", 7777),
            _txn("2026-03-15", 100),
        ]
        result = compute_historical_cashflow(transactions=txns, ending_balance=10000, months=3)
    by_month = {r["month"]: r for r in result}
    assert by_month["2026-03"]["net"] == 100
    assert "2026-04" not in by_month
