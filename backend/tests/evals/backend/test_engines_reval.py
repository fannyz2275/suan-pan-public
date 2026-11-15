"""Spec B Phase 2 — engine module test for app.portfolio.reval.

Includes I4 — reval correctness when every holding has an exact price on as_of.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.portfolio.reval import revalue_at, timeseries


_AS_OF = date(2026, 5, 1)


def test_revalue_single_holding_golden(snapshot_json):
    holdings = [{"ticker": "NVDA", "quantity": 10}]
    prices = {("NVDA", _AS_OF): 820.0}
    total = revalue_at(holdings, _AS_OF, prices, cash=500.0)
    assert {"as_of": _AS_OF.isoformat(), "total_value": total} == snapshot_json


def test_revalue_uses_most_recent_within_staleness_window():
    """If exact-day price missing, use the most recent within max_staleness_days."""
    holdings = [{"ticker": "NVDA", "quantity": 10}]
    prices = {
        ("NVDA", _AS_OF - timedelta(days=3)): 800.0,  # within window
        ("NVDA", _AS_OF - timedelta(days=10)): 700.0,  # outside default window of 7
    }
    total = revalue_at(holdings, _AS_OF, prices, cash=0.0)
    assert total == pytest.approx(8_000.0, abs=1e-6)


def test_revalue_drops_holding_when_price_too_stale():
    holdings = [{"ticker": "NVDA", "quantity": 10}]
    prices = {("NVDA", _AS_OF - timedelta(days=30)): 1_000.0}
    total = revalue_at(holdings, _AS_OF, prices, cash=100.0)
    assert total == 100.0  # only cash


def test_revalue_ignores_future_prices():
    holdings = [{"ticker": "NVDA", "quantity": 10}]
    prices = {("NVDA", _AS_OF + timedelta(days=2)): 900.0}
    total = revalue_at(holdings, _AS_OF, prices, cash=0.0)
    assert total == 0.0


# ---------------------------------------------------------------------------
# I4 — Reval correctness with present prices
# ---------------------------------------------------------------------------

def test_invariant_i4_revalue_matches_qty_times_price_plus_cash():
    holdings = [
        {"ticker": "NVDA", "quantity": 10},
        {"ticker": "AAPL", "quantity": 5},
    ]
    prices = {
        ("NVDA", _AS_OF): 820.0,
        ("AAPL", _AS_OF): 200.0,
    }
    cash = 1_000.0
    expected = cash + 10 * 820.0 + 5 * 200.0
    actual = revalue_at(holdings, _AS_OF, prices, cash)
    assert actual == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# timeseries
# ---------------------------------------------------------------------------

def test_timeseries_two_snapshot_period_golden(snapshot_json):
    snap_a = {
        "snapshot_date": "2026-05-01",
        "cash_value": 0.0,
        "holdings": [{"ticker": "NVDA", "quantity": 10}],
    }
    snap_b = {
        "snapshot_date": "2026-05-03",
        "cash_value": 0.0,
        "holdings": [{"ticker": "NVDA", "quantity": 12}],
    }
    prices = {
        ("NVDA", date(2026, 5, 1)): 800.0,
        ("NVDA", date(2026, 5, 2)): 810.0,
        ("NVDA", date(2026, 5, 3)): 820.0,
        ("NVDA", date(2026, 5, 4)): 830.0,
    }
    series = timeseries(
        [snap_a, snap_b], prices,
        from_date=date(2026, 5, 1), to_date=date(2026, 5, 4),
    )
    # Materialize ISO date strings for stable JSON serialization.
    out = [{"date": p["date"].isoformat(), "total_value": p["total_value"]} for p in series]
    assert out == snapshot_json


def test_timeseries_returns_empty_when_no_snapshot_at_or_before_from_date():
    snap = {
        "snapshot_date": "2026-05-10",
        "cash_value": 0.0,
        "holdings": [],
    }
    series = timeseries(
        [snap], {},
        from_date=date(2026, 5, 1), to_date=date(2026, 5, 5),
    )
    assert series == []


def test_timeseries_each_point_total_value_non_negative():
    snap = {
        "snapshot_date": "2026-05-01",
        "cash_value": 100.0,
        "holdings": [{"ticker": "NVDA", "quantity": 1}],
    }
    prices = {("NVDA", date(2026, 5, 1)): 800.0}
    series = timeseries([snap], prices, from_date=date(2026, 5, 1), to_date=date(2026, 5, 3))
    for point in series:
        assert point["total_value"] >= 0
