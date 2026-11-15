"""Spec B MCP tool tests.

Phase 1: pure-math tool (`compute_annuity`).
Phase 2: engine-wrapper tools (`get_snapshot`, `simulate_decision_tool`,
`monte_carlo_tool`, `project_cashflow_tool`, `find_similar_goal`).
"""
from __future__ import annotations

import math
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.engine import feasibility as feas_mod
from app.mcp import tools as mcp_tools
from app.mcp.tools import (
    compute_annuity,
    find_similar_goal,
    get_snapshot,
    monte_carlo_tool,
    project_cashflow_tool,
    simulate_decision_tool,
)


def test_compute_annuity_solve_for_months_golden(snapshot_json):
    result = compute_annuity(
        solve_for="months", annual_rate=0.07, pmt=500, fv=100_000
    )
    assert result == snapshot_json


def test_compute_annuity_solve_for_fv_golden(snapshot_json):
    result = compute_annuity(
        solve_for="fv", annual_rate=0.07, pmt=500, months=120
    )
    assert result == snapshot_json


def test_compute_annuity_solve_for_pmt_golden(snapshot_json):
    result = compute_annuity(
        solve_for="pmt", annual_rate=0.07, fv=100_000, months=120
    )
    assert result == snapshot_json


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_compute_annuity_invalid_solve_for():
    result = compute_annuity(solve_for="bogus", annual_rate=0.05)
    assert "error" in result
    assert "solve_for" in result["error"]


def test_compute_annuity_rejects_zero_rate():
    result = compute_annuity(
        solve_for="fv", annual_rate=0.0, pmt=500, months=12
    )
    assert "error" in result
    assert "annual_rate" in result["error"]


def test_compute_annuity_rejects_rate_one_or_more():
    result = compute_annuity(
        solve_for="fv", annual_rate=1.0, pmt=500, months=12
    )
    assert "error" in result


def test_compute_annuity_long_horizon_warning():
    """When n > 1200 (100 years) the months result must include a warning."""
    result = compute_annuity(
        solve_for="months", annual_rate=0.001, pmt=1, fv=10_000_000
    )
    assert "warning" in result, result
    assert result["months"] >= 1200


def test_compute_annuity_pmt_round_trips_with_fv():
    """Computed PMT should reproduce the target FV when fed back into solve_for=fv."""
    pmt_result = compute_annuity(
        solve_for="pmt", annual_rate=0.06, fv=50_000, months=60
    )
    fv_result = compute_annuity(
        solve_for="fv",
        annual_rate=0.06,
        pmt=pmt_result["pmt"],
        months=60,
    )
    assert math.isclose(fv_result["fv"], 50_000, rel_tol=1e-3)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"solve_for": "months", "annual_rate": 0.05, "fv": 1000},  # missing pmt
        {"solve_for": "fv", "annual_rate": 0.05, "pmt": 100},      # missing months
        {"solve_for": "pmt", "annual_rate": 0.05, "fv": 100},      # missing months
    ],
)
def test_compute_annuity_missing_required_args(kwargs):
    result = compute_annuity(**kwargs)
    assert "error" in result


# ---------------------------------------------------------------------------
# Phase 2 — engine-wrapper tools.
#
# These read accounts/goals/transactions from the DB before delegating to
# pure engine functions. We patch the loader helpers so the test focuses on
# the wrapper's composition logic, not the SQL chain.
# ---------------------------------------------------------------------------


_TODAY = date(2026, 5, 9)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _TODAY


@pytest.fixture
def freeze_today(monkeypatch):
    monkeypatch.setattr(feas_mod, "date", _FrozenDate)


@pytest.fixture
def fake_accounts() -> list[dict]:
    return [
        {"type": "checking", "balance": 5_000.0},
        {"type": "savings", "balance": 12_000.0},
        {"type": "brokerage", "balance": 60_000.0},
        {"type": "debt", "balance": -8_000.0},
    ]


@pytest.fixture
def fake_goals() -> list[dict]:
    return [
        {
            "id": "g1",
            "name": "Emergency Fund",
            "target_amount": 30_000.0,
            "current_progress": 12_000.0,
            "target_date": "2027-05-01",
        },
    ]


def test_get_snapshot_wraps_compute_snapshot(fake_accounts):
    db = MagicMock()
    with patch.object(mcp_tools, "_load_accounts", return_value=fake_accounts):
        result = get_snapshot(db, "u-test")
    assert result["liquid_assets"] == 17_000.0
    assert result["investment_assets"] == 60_000.0
    assert result["total_liabilities"] == 8_000.0
    assert result["net_worth"] == 69_000.0


def test_get_snapshot_no_accounts_returns_zeros():
    db = MagicMock()
    with patch.object(mcp_tools, "_load_accounts", return_value=[]):
        result = get_snapshot(db, "u-test")
    assert result["net_worth"] == 0
    assert result["liquid_assets"] == 0


def test_simulate_decision_tool_wraps_engine(fake_accounts, fake_goals, freeze_today):
    db = MagicMock()
    with patch.object(mcp_tools, "_load_accounts", return_value=fake_accounts), \
         patch.object(mcp_tools, "_load_active_goals", return_value=fake_goals), \
         patch.object(mcp_tools, "_monthly_income_expenses", return_value=(10_000.0, 6_500.0)):
        result = simulate_decision_tool(
            db, "u-test",
            description="Buy a $5k laptop",
            upfront_cost=5_000.0,
            monthly_delta=-100.0,
        )
    assert result["decision"] == "Buy a $5k laptop"
    # liquid_override pulls from compute_snapshot's liquid_assets
    assert result["liquid_assets_before"] == 17_000.0
    assert result["liquid_assets_after"] == 12_000.0
    assert len(result["goal_impacts"]) == 1


def test_monte_carlo_tool_zero_inputs_error():
    db = MagicMock()
    with patch.object(mcp_tools, "_load_accounts", return_value=[]), \
         patch.object(mcp_tools, "_monthly_income_expenses", return_value=(0.0, 0.0)):
        result = monte_carlo_tool(db, "u-test", years=10)
    assert "error" in result


def test_monte_carlo_tool_negative_years_error():
    db = MagicMock()
    result = monte_carlo_tool(db, "u-test", years=0)
    assert "error" in result
    assert "years" in result["error"]


def test_monte_carlo_tool_uses_snapshot_defaults_for_initial_portfolio():
    db = MagicMock()
    accounts = [
        {"type": "brokerage", "balance": 50_000.0},
        {"type": "checking", "balance": 5_000.0},
    ]
    with patch.object(mcp_tools, "_load_accounts", return_value=accounts), \
         patch.object(mcp_tools, "_monthly_income_expenses", return_value=(8_000.0, 6_000.0)):
        result = monte_carlo_tool(db, "u-test", years=5)
    assert "p50" in result
    assert result["effective_inputs"]["initial_portfolio"] == 50_000.0
    # surplus = 8000 - 6000 = 2000
    assert result["effective_inputs"]["monthly_contribution"] == 2_000.0


def test_project_cashflow_tool_no_recurring_rules_no_rsu():
    db = MagicMock()
    accounts = [
        {"type": "checking", "balance": 5_000.0},
        {"type": "savings", "balance": 10_000.0},
    ]
    with patch.object(mcp_tools, "_load_accounts", return_value=accounts), \
         patch.object(mcp_tools, "_monthly_income_expenses", return_value=(8_000.0, 6_000.0)), \
         patch.object(mcp_tools, "_load_recurring_rules", return_value=[]):
        result = project_cashflow_tool(
            db, "00000000-0000-0000-0000-000000000001", months=3,
        )
    assert len(result) == 3
    for row in result:
        assert row["fixed_inflow"] == 0.0
        assert row["fixed_outflow"] == 0.0


# ---------------------------------------------------------------------------
# find_similar_goal — no engine; deterministic string-similarity logic.
# ---------------------------------------------------------------------------

def _stub_db_for_goals(goal_rows: list[dict]) -> MagicMock:
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = goal_rows
    return db


def test_find_similar_goal_no_existing_goals_returns_empty_match():
    db = _stub_db_for_goals([])
    result = find_similar_goal(db, "u-test", candidate_name="Wedding")
    assert result["match"] is None
    assert result["score"] == 0.0
    assert result["all"] == []


def test_find_similar_goal_strong_match():
    db = _stub_db_for_goals([
        {"id": "g1", "name": "Wedding fund", "target_amount": 30_000, "target_date": "2027-09-01"},
        {"id": "g2", "name": "Down Payment", "target_amount": 150_000, "target_date": "2030-01-01"},
    ])
    result = find_similar_goal(db, "u-test", candidate_name="wedding")
    assert result["match"]["name"] == "Wedding fund"
    assert result["score"] >= 0.5


# ---------------------------------------------------------------------------
# Phase 3 — score_goal + portfolio_get_holdings/exposure/attribution goldens
# + list_recurring_rules.
# ---------------------------------------------------------------------------

from datetime import date as _date
from uuid import uuid4

from app.engine.recurring.schema import (
    Direction as _Direction,
    Frequency as _Frequency,
    RecurringRule as _RecurringRule,
    Source as _Source,
    Status as _Status,
)
from app.mcp.tools import (
    list_recurring_rules,
    portfolio_get_attribution,
    portfolio_get_exposure,
    portfolio_get_holdings,
    score_goal,
)


def test_score_goal_uuid_path(freeze_today):
    """score_goal accepts a UUID and routes through score_goal_feasibility."""
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Emergency Fund",
            "target_amount": 30_000.0,
            "current_progress": 12_000.0,
            "target_date": "2027-05-01",
        }
    ]
    with patch.object(mcp_tools, "_monthly_income_expenses", return_value=(8_000.0, 5_000.0)):
        result = score_goal(
            db, "u-test", "11111111-1111-1111-1111-111111111111"
        )
    assert "feasibility_score" in result
    assert 0 <= result["feasibility_score"] <= 100


def test_score_goal_not_found_returns_error():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.ilike.return_value.execute.return_value.data = []
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    result = score_goal(db, "u-test", "missing")
    assert result["error"] == "goal not found"


def test_score_goal_ambiguous_name_returns_matches():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.ilike.return_value.execute.return_value.data = [
        {"id": "g1", "name": "Wedding", "target_amount": 30_000},
        {"id": "g2", "name": "Wedding", "target_amount": 10_000},
    ]
    result = score_goal(db, "u-test", "wedding")
    assert result["error"] == "goal name is ambiguous"
    assert len(result["matches"]) == 2


# ---------------------------------------------------------------------------
# portfolio_get_holdings golden (single-account-2-holdings)
# ---------------------------------------------------------------------------

def test_portfolio_get_holdings_golden(snapshot_json):
    db = MagicMock()
    snap = {
        "id": "s1",
        "account_id": "acc-1",
        "snapshot_date": "2026-05-01",
        "source": "manual",
        "total_value": 9_200,
        "cash_value": 0,
        "created_at": "2026-05-01T00:00:00Z",
        "holdings": [
            {"ticker": "NVDA", "quantity": 10, "price": 820.0,
             "market_value": 8_200.0, "cost_basis": 6_000.0,
             "unrealized_gain": 2_200.0},
            {"ticker": "AAPL", "quantity": 5, "price": 200.0,
             "market_value": 1_000.0, "cost_basis": 850.0,
             "unrealized_gain": 150.0},
        ],
    }
    with patch.object(mcp_tools, "_user_owns_investment_account", return_value=True), \
         patch("app.portfolio.snapshots.get_latest_snapshot", return_value=snap):
        result = portfolio_get_holdings(
            db, "u-test", account_id="11111111-1111-1111-1111-111111111111",
        )
    assert result == snapshot_json


def test_portfolio_get_holdings_empty_returns_empty_list():
    db = MagicMock()
    with patch.object(mcp_tools, "_user_owns_investment_account", return_value=True), \
         patch("app.portfolio.snapshots.get_latest_snapshot", return_value=None):
        result = portfolio_get_holdings(
            db, "u-test", account_id="11111111-1111-1111-1111-111111111111",
        )
    assert result == []


# ---------------------------------------------------------------------------
# portfolio_get_exposure golden (etf-with-look-through)
# ---------------------------------------------------------------------------

def test_portfolio_get_exposure_etf_look_through_golden(snapshot_json):
    db = MagicMock()
    db.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {"ticker": "VOO", "asset_class": "equity", "sector": None,
         "region": "US", "look_through": [
             {"ticker": "AAPL", "weight": 0.07},
             {"ticker": "MSFT", "weight": 0.06},
         ]},
        {"ticker": "AAPL", "asset_class": "equity", "sector": "Technology",
         "region": "US", "look_through": None},
        {"ticker": "MSFT", "asset_class": "equity", "sector": "Technology",
         "region": "US", "look_through": None},
        {"ticker": "BND", "asset_class": "fixed_income", "sector": None,
         "region": "US", "look_through": None},
    ]

    snap = {
        "id": "s1",
        "account_id": "acc-1",
        "snapshot_date": "2026-05-01",
        "source": "manual",
        "total_value": 15_000,
        "cash_value": 0,
        "created_at": "2026-05-01T00:00:00Z",
        "holdings": [
            {"ticker": "VOO", "quantity": 30, "price": 333.33,
             "market_value": 10_000.0, "cost_basis": None, "unrealized_gain": None},
            {"ticker": "BND", "quantity": 50, "price": 100.0,
             "market_value": 5_000.0, "cost_basis": None, "unrealized_gain": None},
        ],
    }
    with patch.object(mcp_tools, "_user_owns_investment_account", return_value=True), \
         patch("app.portfolio.snapshots.get_latest_snapshot", return_value=snap):
        result = portfolio_get_exposure(
            db, "u-test", dimension="sector",
            account_id="11111111-1111-1111-1111-111111111111",
        )
    assert result == snapshot_json


def test_portfolio_get_exposure_invalid_dimension_returns_error():
    db = MagicMock()
    result = portfolio_get_exposure(db, "u-test", dimension="bogus")
    assert result == [{"error": "dimension must be one of: asset_class, sector, region"}]


# ---------------------------------------------------------------------------
# portfolio_get_attribution golden
# ---------------------------------------------------------------------------

def test_portfolio_get_attribution_golden(snapshot_json):
    db = MagicMock()

    snaps = [
        {
            "id": "s1", "account_id": "acc-1",
            "snapshot_date": "2026-04-01", "source": "manual",
            "total_value": 8_000, "cash_value": 0,
            "created_at": "2026-04-01T00:00:00Z",
            "holdings": [{"ticker": "NVDA", "quantity": 10, "price": 800,
                          "market_value": 8_000, "cost_basis": None,
                          "unrealized_gain": None}],
        },
        {
            "id": "s2", "account_id": "acc-1",
            "snapshot_date": "2026-05-01", "source": "manual",
            "total_value": 9_000, "cash_value": 0,
            "created_at": "2026-05-01T00:00:00Z",
            "holdings": [{"ticker": "NVDA", "quantity": 10, "price": 900,
                          "market_value": 9_000, "cost_basis": None,
                          "unrealized_gain": None}],
        },
    ]

    db.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = [
        {"type": "dividend", "amount": 25.0, "account_id": "acc-1",
         "date": "2026-04-15"},
    ]

    prices = {
        ("NVDA", _date(2026, 4, 1)): 800.0,
        ("NVDA", _date(2026, 5, 1)): 900.0,
    }

    with patch.object(mcp_tools, "_user_owns_investment_account", return_value=True), \
         patch("app.portfolio.snapshots.get_snapshots_in_window", return_value=snaps), \
         patch("app.portfolio.reference.get_prices", return_value=prices), \
         patch("app.portfolio.fred.fetch_fred_series", return_value={}):
        result = portfolio_get_attribution(
            db, "u-test",
            from_date="2026-04-01", to_date="2026-05-01",
            account_id="acc-1",
        )
    assert result == snapshot_json


def test_portfolio_get_attribution_no_accounts_returns_error():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = []
    result = portfolio_get_attribution(
        db, "u-test", from_date="2026-04-01", to_date="2026-05-01",
    )
    assert result == {"error": "no investment accounts found"}


# ---------------------------------------------------------------------------
# list_recurring_rules
# ---------------------------------------------------------------------------

def _make_rule(*, keyword: str, amount: float, freq: _Frequency = _Frequency.MONTHLY,
               direction: _Direction = _Direction.EXPENSE,
               status: _Status = _Status.AUTO_APPLIED) -> _RecurringRule:
    return _RecurringRule(
        user_id=uuid4(),
        keyword=keyword,
        normalized_key_pattern=keyword,
        amount_min=amount,
        amount_max=amount,
        amount_median=amount,
        frequency=freq,
        direction=direction,
        confidence=0.95,
        status=status,
        source=_Source.HEURISTIC,
        occurrences_observed=12,
    )


def test_list_recurring_rules_returns_compact_dicts():
    rules = [_make_rule(keyword="rent", amount=2_000.0)]
    db = MagicMock()
    with patch.object(mcp_tools, "_load_recurring_rules", return_value=rules):
        result = list_recurring_rules(
            db, "00000000-0000-0000-0000-000000000001",
        )
    assert len(result) == 1
    rule = result[0]
    # Compact shape: no UUIDs, no sample_transaction_ids leaked.
    assert "id" not in rule
    assert "sample_transaction_ids" not in rule
    assert rule["keyword"] == "rent"
    assert rule["frequency"] == "monthly"
    assert rule["monthly_equivalent"] == 2_000.0


def test_list_recurring_rules_min_monthly_amount_filter():
    rules = [
        _make_rule(keyword="rent", amount=2_000.0),
        _make_rule(keyword="netflix", amount=15.0),
    ]
    db = MagicMock()
    with patch.object(mcp_tools, "_load_recurring_rules", return_value=rules):
        result = list_recurring_rules(
            db, "00000000-0000-0000-0000-000000000001",
            min_monthly_amount=100,
        )
    assert {r["keyword"] for r in result} == {"rent"}


def test_list_recurring_rules_frequency_filter():
    rules = [
        _make_rule(keyword="rent", amount=2_000, freq=_Frequency.MONTHLY),
        _make_rule(keyword="annual_fee", amount=50, freq=_Frequency.ANNUAL),
    ]
    db = MagicMock()
    with patch.object(mcp_tools, "_load_recurring_rules", return_value=rules):
        result = list_recurring_rules(
            db, "00000000-0000-0000-0000-000000000001",
            frequency="annual",
        )
    assert {r["keyword"] for r in result} == {"annual_fee"}


def test_list_recurring_rules_no_rules_returns_empty():
    db = MagicMock()
    with patch.object(mcp_tools, "_load_recurring_rules", return_value=[]):
        result = list_recurring_rules(
            db, "00000000-0000-0000-0000-000000000001",
        )
    assert result == []
