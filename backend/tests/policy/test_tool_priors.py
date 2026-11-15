"""Unit tests for app.policy.tool_priors — args_hash, log_tool_call,
reorder_tools, wilson_lower_bound. DB is mocked."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.policy import tool_priors as tp


# ---- args_hash ------------------------------------------------------------


def test_args_hash_deterministic_across_key_order():
    a = {"date_from": "2026-01-01", "date_to": "2026-01-31", "category": "Food"}
    b = {"category": "Food", "date_to": "2026-01-31", "date_from": "2026-01-01"}
    assert tp.args_hash(a) == tp.args_hash(b)


def test_args_hash_empty_returns_empty():
    assert tp.args_hash({}) == ""


def test_args_hash_distinguishes_different_args():
    a = {"date_from": "2026-01-01"}
    b = {"date_from": "2026-02-01"}
    assert tp.args_hash(a) != tp.args_hash(b)


def test_args_hash_handles_non_json_native_values():
    """uuids / datetimes etc. should serialize via str() rather than crash."""
    h = tp.args_hash({"id": uuid4()})
    assert isinstance(h, str)
    assert len(h) == 16


# ---- log_tool_call --------------------------------------------------------


def test_log_tool_call_inserts_full_row():
    db = MagicMock()
    tp.log_tool_call(
        db,
        user_id=uuid4(), session_id="s1", message_id=None,
        tool_name="get_transactions", args={"date_from": "2026-01-01"},
        ctx_signature="asking_about_spending",
        succeeded=True, duration_ms=120,
    )

    payload = db.table.return_value.insert.call_args.args[0]
    assert payload["tool_name"] == "get_transactions"
    assert payload["session_id"] == "s1"
    assert payload["ctx_signature"] == "asking_about_spending"
    assert payload["succeeded"] is True
    assert payload["duration_ms"] == 120
    assert len(payload["args_hash"]) == 16


def test_log_tool_call_swallows_db_failure():
    """Hot path — must not raise. Chat turn proceeds even if logging fails."""
    db = MagicMock()
    db.table.side_effect = RuntimeError("DB down")

    # No assertion needed — the test passes if this doesn't raise.
    tp.log_tool_call(
        db, user_id=uuid4(), session_id=None, message_id=None,
        tool_name="x", args={}, ctx_signature="other",
        succeeded=False,
    )


# ---- reorder_tools --------------------------------------------------------


def _named(name):
    """Create a stand-in for genai.types.FunctionDeclaration with a `.name`."""
    obj = SimpleNamespace(name=name)
    return obj


def test_reorder_with_no_priors_preserves_input_order():
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[],
    )
    tools = [_named("a"), _named("b"), _named("c")]
    out = tp.reorder_tools(
        db, user_id=uuid4(), ctx_signature="other", tools=tools,
    )
    assert [t.name for t in out] == ["a", "b", "c"]


def test_reorder_priors_descend_then_unranked_tail():
    """Tools with priors come first (descending utility), tools without
    priors keep their original order at the back."""
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(
        data=[
            {"tool_name": "compare_spending_periods", "utility_score": 0.7},
            {"tool_name": "get_transactions", "utility_score": 0.4},
        ],
    )
    tools = [
        _named("get_snapshot"),  # no prior
        _named("get_transactions"),
        _named("compare_spending_periods"),
        _named("score_goal"),  # no prior
    ]
    out = tp.reorder_tools(
        db, user_id=uuid4(), ctx_signature="asking_about_spending", tools=tools,
    )
    assert [t.name for t in out] == [
        "compare_spending_periods",  # 0.7
        "get_transactions",          # 0.4
        "get_snapshot",              # unranked, kept input order
        "score_goal",                # unranked, kept input order
    ]


def test_reorder_returns_input_unchanged_on_lookup_failure():
    db = MagicMock()
    db.table.side_effect = RuntimeError("DB down")
    tools = [_named("a"), _named("b")]
    out = tp.reorder_tools(
        db, user_id=uuid4(), ctx_signature="other", tools=tools,
    )
    assert out == tools


def test_reorder_handles_empty_tools():
    db = MagicMock()
    out = tp.reorder_tools(
        db, user_id=uuid4(), ctx_signature="other", tools=[],
    )
    assert out == []


# ---- wilson_lower_bound ---------------------------------------------------


def test_wilson_low_volume_penalized_relative_to_high_volume():
    """A 1-for-1 tool (100% but only 1 sample) must NOT outrank a 50-for-60
    tool (~83% with strong evidence)."""
    one_for_one = tp.wilson_lower_bound(1, 1)
    fifty_for_sixty = tp.wilson_lower_bound(50, 60)
    assert fifty_for_sixty > one_for_one


def test_wilson_returns_zero_for_zero_samples():
    assert tp.wilson_lower_bound(0, 0) == 0.0


def test_wilson_zero_successes_returns_zero():
    assert tp.wilson_lower_bound(0, 100) == 0.0


def test_wilson_perfect_score_below_one_for_finite_n():
    """Even 1000-for-1000 stays below 1.0 — Wilson is a lower bound."""
    assert tp.wilson_lower_bound(1000, 1000) < 1.0
