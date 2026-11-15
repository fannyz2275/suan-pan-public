"""Unit tests for the engine-fn-as-MCP-tool wrappers in app/mcp/tools.py.

Each wrapper is a thin "load db data + call pure engine fn" sandwich. The
engine fns themselves are tested in tests/engine/. These tests verify the
loading + default-derivation behavior of the wrappers."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.mcp import tools as mcp_tools


def _profile() -> dict:
    """Profile fixture — no dollar amounts. Income/expenses now come from
    the transaction-derived medians helper, not the profile row (the
    dollar-amount rule)."""
    return {"id": str(uuid4())}


def _patch_medians(income: float, expenses: float):
    """Convenience: patch the income/expense medians helper in app.mcp.tools.
    Tests that care about cashflow values use this rather than seeding raw
    transaction rows through the table-mock chain."""
    return patch(
        "app.mcp.tools._monthly_income_expenses",
        return_value=(income, expenses),
    )


def _account(type_: str = "checking", balance: float = 1000.0, **extra) -> dict:
    return {"id": str(uuid4()), "type": type_, "balance": balance, **extra}


def _goal(
    target_amount: float = 80_000, current_progress: float = 25_000,
    target_date: str = "2030-01-01",
) -> dict:
    return {
        "id": str(uuid4()),
        "target_amount": target_amount,
        "current_progress": current_progress,
        "target_date": target_date,
        "name": "Test Goal",
    }


def _mock_db_with(*, accounts=None, goals=None, profile=None, goal_by_id=None):
    """Wire a MagicMock db to satisfy the typical `_load_*` calls. Each
    table().select()...execute().data path returns the relevant fixture."""
    db = MagicMock()

    def table_router(name):
        m = MagicMock()
        if name == "profiles":
            m.select.return_value.eq.return_value.execute.return_value = SimpleNamespace(
                data=[profile] if profile else [],
            )
        elif name == "accounts":
            m.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
                data=list(accounts or []),
            )
        elif name == "goals":
            # Both _load_active_goals and score_goal hit this — distinguish
            # by the number of .eq calls. Easiest: configure two paths.
            list_chain = m.select.return_value.eq.return_value.eq.return_value
            list_chain.execute.return_value = SimpleNamespace(data=list(goals or []))
            id_chain = m.select.return_value.eq.return_value.eq.return_value.limit.return_value
            id_chain.execute.return_value = SimpleNamespace(
                data=[goal_by_id] if goal_by_id else [],
            )
        return m

    db.table.side_effect = table_router
    return db


# ---- get_snapshot ---------------------------------------------------------


def test_get_snapshot_aggregates_accounts(snapshot_json):
    accounts = [
        _account(type_="checking", balance=10_000),
        _account(type_="brokerage", balance=200_000),
        _account(type_="property", balance=500_000),
    ]
    db = _mock_db_with(accounts=accounts)
    out = mcp_tools.get_snapshot(db, str(uuid4()))
    # Golden locks the full snapshot shape, including liquid_net_worth + liabilities.
    assert out == snapshot_json


def test_get_snapshot_with_no_accounts_returns_zeros(snapshot_json):
    db = _mock_db_with(accounts=[])
    out = mcp_tools.get_snapshot(db, str(uuid4()))
    assert out == snapshot_json


# ---- score_goal ------------------------------------------------------------


def test_score_goal_returns_error_for_missing_goal(snapshot_json):
    db = _mock_db_with(goal_by_id=None, profile=_profile())
    out = mcp_tools.score_goal(db, str(uuid4()), goal_id=str(uuid4()))
    assert out == snapshot_json


def test_score_goal_uses_transaction_derived_surplus():
    """monthly_surplus comes from the transaction-median helper, not
    profile dollar fields (which were dropped in PR-A's migration)."""
    goal = _goal(target_amount=60_000, current_progress=0, target_date="2027-01-01")
    db = _mock_db_with(goal_by_id=goal)

    with _patch_medians(income=10_000, expenses=4_000):  # surplus 6,000
        out = mcp_tools.score_goal(db, str(uuid4()), goal_id=goal["id"])
    assert "feasibility_score" in out
    assert out["feasibility_score"] > 0


# ---- simulate_decision_tool -----------------------------------------------


def test_simulate_decision_passes_decision_fields_through():
    db = _mock_db_with(
        accounts=[_account(type_="checking", balance=50_000)],
        goals=[_goal()],
        profile=_profile(),
    )
    with patch("app.mcp.tools.simulate_decision") as engine_fn:
        engine_fn.return_value = {"liquid_after": 15_000}
        mcp_tools.simulate_decision_tool(
            db, str(uuid4()),
            description="Buy a $35k car",
            upfront_cost=35_000, monthly_delta=-500,
        )

    decision_arg = engine_fn.call_args.kwargs["decision"]
    assert decision_arg["description"] == "Buy a $35k car"
    assert decision_arg["upfront_cost"] == 35_000
    assert decision_arg["monthly_delta"] == -500
    assert decision_arg["asset_value"] == 0  # default


def test_simulate_decision_passes_user_data_through():
    accounts = [_account(type_="checking", balance=50_000)]
    goals = [_goal()]
    db = _mock_db_with(accounts=accounts, goals=goals, profile=_profile())

    with patch("app.mcp.tools.simulate_decision") as engine_fn, \
         _patch_medians(income=15_000, expenses=5_400):
        engine_fn.return_value = {}
        mcp_tools.simulate_decision_tool(
            db, str(uuid4()), description="x",
        )

    kwargs = engine_fn.call_args.kwargs
    assert kwargs["accounts"] == accounts
    assert kwargs["goals"] == goals
    assert kwargs["monthly_income"] == 15_000
    assert kwargs["monthly_expenses"] == 5_400


# ---- monte_carlo_tool -----------------------------------------------------


def test_monte_carlo_defaults_initial_portfolio_to_investment_assets():
    db = _mock_db_with(
        accounts=[
            _account(type_="checking", balance=10_000),
            _account(type_="brokerage", balance=300_000),
        ],
        profile=_profile(),
    )
    with patch("app.mcp.tools.run_monte_carlo") as engine_fn, \
         _patch_medians(income=10_000, expenses=4_000):
        engine_fn.return_value = {"p50": 0}
        mcp_tools.monte_carlo_tool(db, str(uuid4()), years=10)

    kwargs = engine_fn.call_args.kwargs
    assert kwargs["initial_portfolio"] == 300_000
    # default monthly_contribution = monthly surplus = 10_000 - 4_000 = 6_000
    assert kwargs["monthly_contribution"] == 6_000
    assert kwargs["years"] == 10


def test_monte_carlo_explicit_overrides_take_precedence():
    db = _mock_db_with(
        accounts=[_account(type_="brokerage", balance=300_000)],
        profile=_profile(),
    )
    with patch("app.mcp.tools.run_monte_carlo") as engine_fn:
        engine_fn.return_value = {}
        mcp_tools.monte_carlo_tool(
            db, str(uuid4()),
            years=20, monthly_contribution=2_000, initial_portfolio=100_000,
            target_amount=1_500_000,
        )

    kwargs = engine_fn.call_args.kwargs
    assert kwargs["initial_portfolio"] == 100_000
    assert kwargs["monthly_contribution"] == 2_000
    assert kwargs["target_amount"] == 1_500_000


def test_monte_carlo_clamps_negative_surplus_with_existing_portfolio():
    """If income < expenses but the user has investments, contribution=0 and
    the engine still runs — portfolio alone can grow."""
    db = _mock_db_with(
        accounts=[_account(type_="brokerage", balance=50_000)],
        profile=_profile(),
    )

    with patch("app.mcp.tools.run_monte_carlo") as engine_fn, \
         _patch_medians(income=2_000, expenses=5_000):  # surplus ≈ -3k
        engine_fn.return_value = {}
        mcp_tools.monte_carlo_tool(db, str(uuid4()), years=10)

    kwargs = engine_fn.call_args.kwargs
    assert kwargs["monthly_contribution"] == 0
    assert kwargs["initial_portfolio"] == 50_000


# ---- R11-4: monte_carlo_tool input validation --------------------------------


def test_monte_carlo_years_zero_returns_error():
    """R11-4: years=0 must return an error dict, not silently run the engine."""
    db = _mock_db_with(accounts=[], profile=_profile())
    with patch("app.mcp.tools.run_monte_carlo") as engine_fn, \
         _patch_medians(income=5_000, expenses=3_000):
        engine_fn.return_value = {}
        result = mcp_tools.monte_carlo_tool(db, str(uuid4()), years=0)

    assert "error" in result
    engine_fn.assert_not_called()


def test_monte_carlo_years_negative_returns_error():
    """Negative years must also return an error dict."""
    db = _mock_db_with(accounts=[], profile=_profile())
    with patch("app.mcp.tools.run_monte_carlo") as engine_fn, \
         _patch_medians(income=5_000, expenses=3_000):
        engine_fn.return_value = {}
        result = mcp_tools.monte_carlo_tool(db, str(uuid4()), years=-5)

    assert "error" in result
    engine_fn.assert_not_called()


def test_monte_carlo_both_zero_returns_error():
    """R11-4: if both initial_portfolio=0 and monthly_contribution=0 (explicit or
    default-derived), return an error rather than a trivially uninformative result."""
    db = _mock_db_with(accounts=[], profile=_profile())
    with patch("app.mcp.tools.run_monte_carlo") as engine_fn, \
         _patch_medians(income=0, expenses=0):
        engine_fn.return_value = {}
        result = mcp_tools.monte_carlo_tool(
            db, str(uuid4()), years=30,
            initial_portfolio=0, monthly_contribution=0,
        )

    assert "error" in result
    engine_fn.assert_not_called()


# ---- project_cashflow_tool ------------------------------------------------


def test_project_cashflow_collects_rsu_vesting_events():
    """RSU accounts contribute their vesting_schedule entries as vesting_events."""
    rsu_a = _account(type_="rsu", balance=0, vesting_schedule=[
        {"date": "2026-06-01", "value": 10_000},
    ])
    rsu_b = _account(type_="rsu", balance=0, vesting_schedule=[
        {"date": "2026-09-01", "value": 5_000},
    ])
    accounts = [_account(type_="checking", balance=20_000), rsu_a, rsu_b]
    db = _mock_db_with(accounts=accounts, profile=_profile())

    with patch("app.mcp.tools.project_cashflow") as engine_fn:
        engine_fn.return_value = []
        mcp_tools.project_cashflow_tool(db, str(uuid4()), months=6)

    kwargs = engine_fn.call_args.kwargs
    assert kwargs["months"] == 6
    assert kwargs["liquid_assets"] == 20_000  # only the checking account
    assert kwargs["vesting_events"] == [
        {"date": "2026-06-01", "value": 10_000},
        {"date": "2026-09-01", "value": 5_000},
    ]
    # Recurring rules must NOT be passed — the monthly_income/expenses medians
    # already include recurring amounts from transaction history, so passing
    # them again would double-count fixed charges (G-038).
    assert "recurring_rules" not in kwargs


def test_project_cashflow_no_double_counting_of_recurring():
    """G-038 regression: project_cashflow_tool must not pass recurring_rules
    alongside transaction-derived monthly income/expenses. Both represent the
    same real payments; combining them inflates the projection.

    With liquid=$84,284, surplus=$9,621/mo, and 6 months:
      Expected balance at month 6 = $84,284 + 6×$9,621 = $141,010
    If recurring rules were double-counted the balance would be higher.
    """
    from datetime import date
    accounts = [_account(type_="checking", balance=84_284)]
    db = _mock_db_with(accounts=accounts, profile=_profile())

    with _patch_medians(income=11_683, expenses=2_062):  # surplus ≈ $9,621
        result = mcp_tools.project_cashflow_tool(db, str(uuid4()), months=6)

    # Month 6 balance without double-counting = 84284 + 6*9621 = 141,810
    # (small rounding: income 11683 - expenses 2062 = 9621)
    expected = round(84_284 + 6 * (11_683 - 2_062), 2)
    assert result[-1]["balance"] == expected


# ---- profile-derived helpers -----------------------------------------------


def test_monthly_income_expenses_returns_zeros_for_cold_start_user():
    """No transactions → median helper returns None → wrapper returns (0, 0).
    Cold-start users get a zero-surplus baseline."""
    db = MagicMock()
    with patch(
        "app.engine.kpis.monthly_income_expense_medians", return_value=None,
    ):
        income, expenses = mcp_tools._monthly_income_expenses(db, str(uuid4()))
    assert income == 0.0
    assert expenses == 0.0


def test_monthly_income_expenses_passes_through_medians():
    """When the helper returns medians, the wrapper passes them through."""
    db = MagicMock()
    with patch(
        "app.engine.kpis.monthly_income_expense_medians",
        return_value=(8_000.0, 3_500.0),
    ):
        income, expenses = mcp_tools._monthly_income_expenses(db, str(uuid4()))
    assert income == 8_000.0
    assert expenses == 3_500.0
