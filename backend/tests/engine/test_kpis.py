"""Tests for engine/kpis.py and engine/snapshot.net_worth_at.

The KPI module talks to the supabase client; we mock it with a small
table-router that returns canned rows per query. This keeps the tests
fast and deterministic without needing a live DB.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.engine import kpis
from uuid import uuid4

from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)
from app.engine.snapshot import net_worth_at


# ---- DB mock ----------------------------------------------------------------


class FakeQuery:
    """Fluent chain that records calls and returns the seeded rows on .execute()."""

    def __init__(self, rows: list[dict]):
        self._rows = rows

    # All chain methods return self so the test can ignore filtering details.
    def select(self, *_a, **_kw): return self
    def eq(self, *_a, **_kw): return self
    def gte(self, *_a, **_kw): return self
    def lte(self, *_a, **_kw): return self
    def in_(self, *_a, **_kw): return self
    def order(self, *_a, **_kw): return self
    def limit(self, *_a, **_kw): return self
    def execute(self): return SimpleNamespace(data=list(self._rows))


def _fake_db(table_rows: dict[str, list[dict]]):
    db = MagicMock()
    db.table.side_effect = lambda name: FakeQuery(table_rows.get(name, []))
    return db


# ---- recurring rule helper -------------------------------------------------


def _rule(direction: Direction, amount: float, freq: Frequency = Frequency.MONTHLY):
    return RecurringRule(
        user_id=uuid4(), keyword="test",
        normalized_key_pattern="test",
        amount_min=amount, amount_max=amount, amount_median=amount,
        frequency=freq, direction=direction,
        confidence=0.9, status=Status.USER_CONFIRMED, source=Source.HEURISTIC,
    )


# ============================================================================
# net_worth_at
# ============================================================================


def test_net_worth_at_returns_none_when_no_history():
    db = _fake_db({
        "accounts": [{"id": "a1", "type": "checking"}],
        "account_balance_history": [],
    })
    assert net_worth_at(db, user_id="u", asof=datetime.now(timezone.utc)) is None


def test_net_worth_at_returns_none_when_no_accounts():
    db = _fake_db({"accounts": [], "account_balance_history": []})
    assert net_worth_at(db, user_id="u", asof=datetime.now(timezone.utc)) is None


def test_net_worth_at_picks_latest_per_account():
    """Same account, multiple history rows ≤ asof — the most recent wins."""
    asof = datetime(2026, 6, 1, tzinfo=timezone.utc)
    db = _fake_db({
        "accounts": [{"id": "a1", "type": "checking"}],
        "account_balance_history": [
            # Returned newest-first by the .order(desc=True) query.
            {"account_id": "a1", "balance": 200, "as_of": "2026-05-01T00:00:00+00:00"},
            {"account_id": "a1", "balance": 100, "as_of": "2026-04-01T00:00:00+00:00"},
        ],
    })
    assert net_worth_at(db, user_id="u", asof=asof) == 200


def test_net_worth_at_subtracts_debt():
    db = _fake_db({
        "accounts": [
            {"id": "a1", "type": "checking"},
            {"id": "d1", "type": "debt"},
        ],
        "account_balance_history": [
            {"account_id": "a1", "balance": 1000, "as_of": "2026-01-01T00:00:00+00:00"},
            {"account_id": "d1", "balance": -300, "as_of": "2026-01-01T00:00:00+00:00"},
        ],
    })
    nw = net_worth_at(db, user_id="u", asof=datetime(2026, 6, 1, tzinfo=timezone.utc))
    # 1000 (checking) − 300 (debt, abs) = 700.
    assert nw == 700


def test_net_worth_at_ignores_inactive_accounts():
    """An account row that isn't in the active-accounts query is dropped from the
    sum even if history rows exist for it."""
    db = _fake_db({
        "accounts": [{"id": "a1", "type": "checking"}],  # a2 missing → inactive
        "account_balance_history": [
            {"account_id": "a1", "balance": 500, "as_of": "2026-01-01T00:00:00+00:00"},
            {"account_id": "a2", "balance": 9999, "as_of": "2026-01-01T00:00:00+00:00"},
        ],
    })
    assert net_worth_at(db, user_id="u", asof=datetime(2026, 6, 1, tzinfo=timezone.utc)) == 500


# ============================================================================
# liquidity_ratio
# ============================================================================


def test_liquidity_ratio_none_when_no_recurring_outflow():
    db = _fake_db({"accounts": [{"balance": 5000, "type": "checking"}]})
    assert kpis.liquidity_ratio(db, user_id="u", recurring_rules=[]) is None
    # Income-only recurring rules also yield None — there's no burn to divide by.
    only_income = [_rule(Direction.INCOME, 3000)]
    assert kpis.liquidity_ratio(db, user_id="u", recurring_rules=only_income) is None


def test_liquidity_ratio_basic():
    db = _fake_db({
        "accounts": [
            {"balance": 8000, "type": "checking"},
            {"balance": 2000, "type": "savings"},
        ],
    })
    rules = [_rule(Direction.EXPENSE, 2500)]  # $2.5k/mo recurring outflow
    # 10000 / 2500 = 4.0 months of runway
    assert kpis.liquidity_ratio(db, user_id="u", recurring_rules=rules) == pytest.approx(4.0)


def test_liquidity_ratio_excludes_investment_accounts():
    """Brokerage / retirement should not count as cash equivalents."""
    db = _fake_db({"accounts": []})  # filter is applied in-query; mock returns nothing
    rules = [_rule(Direction.EXPENSE, 1000)]
    # No liquid accounts returned → cash_total=0 → ratio=0.0 (not None — None
    # is reserved for "no recurring outflow, can't compute").
    assert kpis.liquidity_ratio(db, user_id="u", recurring_rules=rules) == 0.0


# ============================================================================
# savings_rate
# ============================================================================


def test_savings_rate_none_when_no_transactions():
    db = _fake_db({"transactions": []})
    assert kpis.savings_rate(db, user_id="u") is None


def test_savings_rate_none_when_no_income():
    db = _fake_db({"transactions": [
        {"date": "2026-04-15", "amount": -100, "category": "food"},
    ]})
    # No positive-amount rows → income median is 0 → can't divide.
    assert kpis.savings_rate(db, user_id="u") is None


def test_savings_rate_basic_two_months():
    db = _fake_db({"transactions": [
        # Month A: income 5000, expenses 3000.
        {"date": "2026-03-01", "amount": 5000, "category": "income"},
        {"date": "2026-03-15", "amount": -1500, "category": "food"},
        {"date": "2026-03-20", "amount": -1500, "category": "housing"},
        # Month B: income 5000, expenses 4000.
        {"date": "2026-04-01", "amount": 5000, "category": "income"},
        {"date": "2026-04-15", "amount": -2000, "category": "food"},
        {"date": "2026-04-20", "amount": -2000, "category": "housing"},
    ]})
    # median income = 5000, median expense = 3500. Rate = (5000−3500)/5000 = 0.30.
    rate = kpis.savings_rate(db, user_id="u", today=date(2026, 5, 1))
    assert rate == pytest.approx(0.30)


def test_savings_rate_excludes_transfers():
    """Transfer rows are internal moves and must not count as income or expense."""
    db = _fake_db({"transactions": [
        {"date": "2026-03-01", "amount": 5000, "category": "income"},
        {"date": "2026-03-02", "amount": -1000, "category": "food"},
        # Internal transfer — should be ignored.
        {"date": "2026-03-03", "amount": 10_000, "category": "transfer"},
        {"date": "2026-03-04", "amount": -10_000, "category": "transfer"},
    ]})
    # Income median = 5000, expense median = 1000 → (5000−1000)/5000 = 0.80.
    rate = kpis.savings_rate(db, user_id="u", today=date(2026, 5, 1))
    assert rate == pytest.approx(0.80)


# ============================================================================
# nw_yoy_growth
# ============================================================================


def test_nw_yoy_growth_none_when_no_history():
    db = _fake_db({"account_balance_history": []})
    assert kpis.nw_yoy_growth(db, user_id="u") is None


def test_nw_yoy_growth_none_when_history_under_90_days():
    """An 89-day-old history row must return None — the rule is ≥90d to compute."""
    today = date(2026, 6, 1)
    earliest_dt = datetime.combine(today - timedelta(days=89), datetime.min.time(), tzinfo=timezone.utc)
    db = _fake_db({
        "account_balance_history": [{"as_of": earliest_dt.isoformat()}],
    })
    assert kpis.nw_yoy_growth(db, user_id="u", today=today) is None


def test_nw_yoy_growth_annualizes_short_window(monkeypatch):
    """At 180 days old, annualized growth = (NW_now − NW_then)/NW_then × 365/180."""
    today = date(2026, 6, 1)
    earliest_iso = (today - timedelta(days=180)).isoformat() + "T00:00:00+00:00"
    db = _fake_db({
        "account_balance_history": [{"as_of": earliest_iso}],
        "accounts": [{"id": "a1", "type": "checking", "balance": 110_000}],
    })

    # Stub compute_snapshot + net_worth_at to avoid re-deriving them here.
    monkeypatch.setattr(
        "app.engine.snapshot.compute_snapshot",
        lambda accounts: {"net_worth": 110_000},
    )
    monkeypatch.setattr(
        "app.engine.snapshot.net_worth_at",
        lambda db, *, user_id, asof: 100_000.0,
    )

    growth = kpis.nw_yoy_growth(db, user_id="u", today=today)
    # (110000 − 100000) / 100000 = 0.10 over 180d → annualized ≈ 0.10 × (365/180) ≈ 0.2028.
    assert growth == pytest.approx(0.10 * 365 / 180)


def test_nw_yoy_growth_none_when_nw_then_zero(monkeypatch):
    today = date(2026, 6, 1)
    earliest_iso = (today - timedelta(days=180)).isoformat() + "T00:00:00+00:00"
    db = _fake_db({
        "account_balance_history": [{"as_of": earliest_iso}],
        "accounts": [{"id": "a1", "type": "checking", "balance": 5000}],
    })
    monkeypatch.setattr(
        "app.engine.snapshot.compute_snapshot",
        lambda accounts: {"net_worth": 5000},
    )
    # Historical NW = 0 → can't divide → None.
    monkeypatch.setattr(
        "app.engine.snapshot.net_worth_at",
        lambda db, *, user_id, asof: 0.0,
    )
    assert kpis.nw_yoy_growth(db, user_id="u", today=today) is None


# ============================================================================
# yield_on_net_worth
# ============================================================================


def test_yield_on_net_worth_none_when_no_investment_accounts():
    db = _fake_db({"accounts": []})
    assert kpis.yield_on_net_worth(db, user_id="u") is None


def test_yield_on_net_worth_none_with_one_month_of_history():
    """Need ≥2 months to compute month-over-month growth."""
    db = _fake_db({
        "accounts": [{"id": "i1", "type": "brokerage"}],
        "account_balance_history": [
            {"account_id": "i1", "balance": 50000, "as_of": "2026-04-15T00:00:00+00:00"},
        ],
    })
    assert kpis.yield_on_net_worth(db, user_id="u", today=date(2026, 5, 1)) is None


def test_yield_on_net_worth_basic():
    """Investment grew 1k/mo on average; expenses median 2.5k → 1000/2500 = 0.4."""
    db_calls: dict[str, list[dict]] = {
        "accounts": [{"id": "i1", "type": "brokerage"}],
        "account_balance_history": [
            {"account_id": "i1", "balance": 50_000, "as_of": "2026-02-15T00:00:00+00:00"},
            {"account_id": "i1", "balance": 51_000, "as_of": "2026-03-15T00:00:00+00:00"},
            {"account_id": "i1", "balance": 52_000, "as_of": "2026-04-15T00:00:00+00:00"},
        ],
        "transactions": [
            {"date": "2026-02-01", "amount": 5000, "category": "income"},
            {"date": "2026-02-15", "amount": -2500, "category": "food"},
            {"date": "2026-03-01", "amount": 5000, "category": "income"},
            {"date": "2026-03-15", "amount": -2500, "category": "housing"},
        ],
    }
    db = _fake_db(db_calls)
    y = kpis.yield_on_net_worth(db, user_id="u", today=date(2026, 5, 1))
    # monthly_total: Feb=50k, Mar=51k, Apr=52k → growths [1000, 1000] → median 1000.
    # expense median 2500 → yield = 1000 / 2500 = 0.4.
    assert y == pytest.approx(0.4)


def test_yield_on_net_worth_none_when_no_expenses():
    db = _fake_db({
        "accounts": [{"id": "i1", "type": "brokerage"}],
        "account_balance_history": [
            {"account_id": "i1", "balance": 50_000, "as_of": "2026-02-15T00:00:00+00:00"},
            {"account_id": "i1", "balance": 52_000, "as_of": "2026-03-15T00:00:00+00:00"},
        ],
        "transactions": [
            {"date": "2026-02-01", "amount": 5000, "category": "income"},
            # No expenses — denominator is 0, so KPI is undefined.
        ],
    })
    assert kpis.yield_on_net_worth(db, user_id="u", today=date(2026, 5, 1)) is None
