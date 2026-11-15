"""Spec B Phase 3 — MCP tool tests for transaction + goal CRUD tools.

Companion file to `test_tools_mcp.py`; keeps the per-function mocking close to
the assertions while leaving Phase 1/2 cases (compute_annuity, engine wrappers)
in the original file.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.mcp.tools import (
    bulk_recategorize,
    compare_spending_periods,
    delete_goal,
    detect_transfers,
    find_goal_by_name,
    get_spending_by_category,
    get_transactions,
    update_goal,
    update_transaction_category,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_select_all(rows: list[dict]) -> MagicMock:
    """A MagicMock whose deepest .execute().data == rows for every chain shape."""
    db = MagicMock()
    table = db.table.return_value
    # Cover every chain shape used by the tools below by collapsing the chain
    # to MagicMock — anything resolved on `table` returns the same chain proxy
    # by default; we override .execute().data on the leaf.
    table.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.range.return_value.execute.return_value.data = rows
    table.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value.data = rows
    table.select.return_value.eq.return_value.gte.return_value.lte.return_value.lt.return_value.execute.return_value.data = rows
    table.select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value.data = rows
    table.select.return_value.eq.return_value.gte.return_value.lte.return_value.ilike.return_value.order.return_value.execute.return_value.data = rows
    table.select.return_value.eq.return_value.gte.return_value.lte.return_value.ilike.return_value.order.return_value.range.return_value.execute.return_value.data = rows
    table.select.return_value.eq.return_value.gte.return_value.lte.return_value.ilike.return_value.ilike.return_value.order.return_value.range.return_value.execute.return_value.data = rows
    return db


# ---------------------------------------------------------------------------
# get_transactions
# ---------------------------------------------------------------------------

def test_get_transactions_returns_rows():
    rows = [
        {"id": "t1", "date": "2026-04-01", "description": "Coffee",
         "amount": -4.50, "category": "Food", "account_id": "a1"},
        {"id": "t2", "date": "2026-04-02", "description": "Salary",
         "amount": 5000, "category": "Income", "account_id": "a1"},
    ]
    db = _stub_select_all(rows)
    result = get_transactions(
        db, "u-test", date_from="2026-04-01", date_to="2026-04-30",
    )
    assert result == rows


def test_get_transactions_amount_filter_applied_in_python():
    rows = [
        {"id": "t1", "amount": -25, "date": "2026-04-01", "description": "x", "category": "Food", "account_id": "a"},
        {"id": "t2", "amount": -150, "date": "2026-04-02", "description": "y", "category": "Food", "account_id": "a"},
        {"id": "t3", "amount": 5000, "date": "2026-04-03", "description": "z", "category": "Income", "account_id": "a"},
    ]
    db = _stub_select_all(rows)
    result = get_transactions(
        db, "u-test", date_from="2026-04-01", date_to="2026-04-30",
        min_amount=100,
    )
    assert {r["id"] for r in result} == {"t2", "t3"}


def test_get_transactions_empty_returns_empty():
    db = _stub_select_all([])
    result = get_transactions(
        db, "u-test", date_from="2026-04-01", date_to="2026-04-30",
    )
    assert result == []


# ---------------------------------------------------------------------------
# get_spending_by_category
# ---------------------------------------------------------------------------

def test_get_spending_by_category_aggregates_negatives():
    rows = [
        {"amount": -50, "category": "Food"},
        {"amount": -25, "category": "Food"},
        {"amount": -100, "category": "Transport"},
    ]
    db = _stub_select_all(rows)
    result = get_spending_by_category(db, "u-test", "2026-04-01", "2026-04-30")
    by_cat = {r["category"]: r for r in result}
    assert by_cat["Food"]["total"] == 75.0
    assert by_cat["Food"]["count"] == 2
    assert by_cat["Food"]["avg_transaction"] == 37.5
    assert by_cat["Transport"]["total"] == 100.0


def test_get_spending_by_category_zero_spend_period():
    db = _stub_select_all([])
    assert get_spending_by_category(db, "u-test", "2026-04-01", "2026-04-30") == []


def test_get_spending_by_category_other_bucket_for_null_category():
    rows = [{"amount": -10, "category": None}]
    db = _stub_select_all(rows)
    result = get_spending_by_category(db, "u-test", "2026-04-01", "2026-04-30")
    assert result[0]["category"] == "Other"


# ---------------------------------------------------------------------------
# detect_transfers
# ---------------------------------------------------------------------------

def test_detect_transfers_keyword_match():
    rows = [
        {"id": "t1", "date": "2026-04-01", "description": "Zelle to Mom",
         "amount": -50, "category": "Other"},
        {"id": "t2", "date": "2026-04-02", "description": "Coffee",
         "amount": -4, "category": "Food"},
    ]
    db = _stub_select_all(rows)
    result = detect_transfers(
        db, "u-test", date_from="2026-04-01", date_to="2026-04-30",
    )
    ids = {r["id"] for r in result}
    assert "t1" in ids and "t2" not in ids


def test_detect_transfers_round_amount_no_keyword():
    rows = [
        {"id": "t1", "date": "2026-04-01", "description": "Random",
         "amount": -1000, "category": "Other"},
    ]
    db = _stub_select_all(rows)
    result = detect_transfers(
        db, "u-test", date_from="2026-04-01", date_to="2026-04-30",
    )
    assert any("round amount" in r["reason"] for r in result)


def test_detect_transfers_categorized_as_transfer():
    rows = [
        {"id": "t1", "date": "2026-04-01", "description": "abcd",
         "amount": -50, "category": "transfer"},
    ]
    db = _stub_select_all(rows)
    result = detect_transfers(
        db, "u-test", date_from="2026-04-01", date_to="2026-04-30",
    )
    assert any("categorized as transfer" in r["reason"] for r in result)


def test_detect_transfers_no_signals_returns_empty():
    rows = [
        {"id": "t1", "date": "2026-04-01", "description": "Coffee",
         "amount": -4.50, "category": "Food"},
    ]
    db = _stub_select_all(rows)
    assert detect_transfers(
        db, "u-test", date_from="2026-04-01", date_to="2026-04-30",
    ) == []


# ---------------------------------------------------------------------------
# update_transaction_category
# ---------------------------------------------------------------------------

def test_update_transaction_category_invalid_returns_error():
    db = MagicMock()
    result = update_transaction_category(db, "u-test", "t1", "BogusCategory")
    assert result["ok"] is False
    assert result["error"] == "invalid_category"
    assert "allowed" in result


def test_update_transaction_category_not_found():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    result = update_transaction_category(db, "u-test", "missing", "Food")
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# compare_spending_periods
# ---------------------------------------------------------------------------

def test_compare_spending_periods_pct_change_null_when_a_zero():
    """When period A has zero spend in a category, pct_change must be null."""
    rows_a: list[dict] = []
    rows_b = [{"amount": -100, "category": "Food"}]
    db = MagicMock()
    # Both calls hit the same stub; vary by call count.
    call_counter = {"n": 0}

    def _exec(*_a, **_k):
        call_counter["n"] += 1
        out = MagicMock()
        out.data = rows_a if call_counter["n"] == 1 else rows_b
        return out

    db.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.lt.return_value.execute.side_effect = _exec
    result = compare_spending_periods(
        db, "u-test",
        period_a_start="2026-03-01", period_a_end="2026-03-31",
        period_b_start="2026-04-01", period_b_end="2026-04-30",
    )
    food = next(c for c in result["by_category"] if c["category"] == "Food")
    assert food["pct_change"] is None
    assert food["period_a"] == 0
    assert food["period_b"] == 100


# ---------------------------------------------------------------------------
# bulk_recategorize
# ---------------------------------------------------------------------------

def test_bulk_recategorize_dry_run_does_not_update():
    rows = [
        {"id": "t1", "date": "2026-04-01", "description": "Venmo to Alice",
         "amount": -50, "category": "Other"},
    ]
    db = _stub_select_all(rows)
    result = bulk_recategorize(
        db, "u-test",
        description_pattern="venmo", new_category="Transfer",
        date_from="2026-04-01", date_to="2026-04-30",
        dry_run=True,
    )
    assert result["mode"] == "preview"
    assert result["updated_count"] == 0
    assert len(result["matched"]) == 1


def test_bulk_recategorize_no_matches_short_circuits():
    rows = [
        {"id": "t1", "date": "2026-04-01", "description": "Coffee",
         "amount": -4, "category": "Food"},
    ]
    db = _stub_select_all(rows)
    result = bulk_recategorize(
        db, "u-test",
        description_pattern="venmo", new_category="Transfer",
        date_from="2026-04-01", date_to="2026-04-30",
        dry_run=False,
    )
    assert result["matched"] == []
    assert result["mode"] == "preview"


def test_bulk_recategorize_invalid_category_returns_error():
    db = MagicMock()
    result = bulk_recategorize(
        db, "u-test",
        description_pattern="x", new_category="bogus",
        date_from="2026-04-01", date_to="2026-04-30",
    )
    assert result["mode"] == "error"
    assert result["error"] == "invalid_category"


# ---------------------------------------------------------------------------
# update_goal / delete_goal
# ---------------------------------------------------------------------------

def _stub_resolve_goal(rows_for_uuid: list[dict] | None = None,
                      rows_for_name: list[dict] | None = None) -> MagicMock:
    """Stub _resolve_goal_id's two query chains: by id and by ilike(name)."""
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = rows_for_uuid or []
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.ilike.return_value.execute.return_value.data = rows_for_name or []
    return db


def test_update_goal_not_found():
    db = _stub_resolve_goal()
    result = update_goal(db, "u-test", goal_id="ghost", target_amount=10000)
    assert result["error"] == "goal not found"


def test_update_goal_ambiguous_name():
    db = _stub_resolve_goal(rows_for_name=[
        {"id": "g1", "name": "Wedding", "target_amount": 30_000},
        {"id": "g2", "name": "Wedding venue", "target_amount": 10_000},
    ])
    result = update_goal(db, "u-test", goal_id="wedding", target_amount=15_000)
    assert result["error"] == "goal name is ambiguous"
    assert len(result["matches"]) == 2


def test_update_goal_no_op_when_no_fields_passed():
    db = _stub_resolve_goal(rows_for_name=[
        {"id": "g1", "name": "Wedding", "target_amount": 30_000,
         "target_date": "2027-09-01"},
    ])
    result = update_goal(db, "u-test", goal_id="wedding")
    assert result["error"] == "no fields to update"


def test_delete_goal_not_found():
    db = _stub_resolve_goal()
    result = delete_goal(db, "u-test", goal_id="ghost")
    assert result["error"] == "goal not found"


# ---------------------------------------------------------------------------
# find_goal_by_name
# ---------------------------------------------------------------------------

def test_find_goal_by_name_no_existing_goals():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    result = find_goal_by_name(db, "u-test", name="Wedding")
    assert result["error"] == "goal not found"
    assert result["all_goal_names"] == []


def test_find_goal_by_name_returns_match_above_threshold():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "g1", "name": "Wedding fund", "target_amount": 30_000,
         "target_date": "2027-09-01", "feasibility_score": 75,
         "status": "at_risk", "current_progress": 5_000},
    ]
    result = find_goal_by_name(db, "u-test", name="wedding")
    assert result["id"] == "g1"
    assert result["match_score"] >= 0.3


def test_find_goal_by_name_no_match_below_threshold():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "g1", "name": "Down Payment", "target_amount": 100_000,
         "target_date": "2030-01-01", "feasibility_score": None,
         "status": None, "current_progress": 0},
    ]
    result = find_goal_by_name(db, "u-test", name="zxqq")
    assert result.get("error") == "goal not found"
    assert result["all_goal_names"] == ["Down Payment"]
