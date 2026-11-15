"""Tests for in-process tool-call recorder used by Spec C."""
import importlib

import pytest


@pytest.fixture
def fresh_module(monkeypatch):
    """Reimport with the env var of choice and return a fresh module."""
    def _factory(eval_mocks: bool):
        if eval_mocks:
            monkeypatch.setenv("EVAL_MOCKS", "1")
        else:
            monkeypatch.delenv("EVAL_MOCKS", raising=False)
        from app.eval import context as ctx
        importlib.reload(ctx)
        return ctx
    return _factory


def test_record_and_get_returns_recorded_calls(fresh_module):
    ctx = fresh_module(eval_mocks=True)
    ctx.record_tool_call("sess-1", "list_transactions",
                         {"date_from": "2026-04-01"}, {"rows": [{"id": 1}]})
    ctx.record_tool_call("sess-1", "get_recurring_rules", {}, {"rules": []})
    assert ctx.get_tool_calls("sess-1") == [
        {"name": "list_transactions",
         "args": {"date_from": "2026-04-01"},
         "result_data": {"rows": [{"id": 1}]}},
        {"name": "get_recurring_rules", "args": {}, "result_data": {"rules": []}},
    ]


def test_record_is_noop_when_eval_mocks_unset(fresh_module):
    ctx = fresh_module(eval_mocks=False)
    ctx.record_tool_call("sess-1", "list_transactions", {}, {})
    assert ctx.get_tool_calls("sess-1") == []


def test_get_returns_empty_list_for_unknown_session(fresh_module):
    ctx = fresh_module(eval_mocks=True)
    assert ctx.get_tool_calls("never-seen") == []


def test_clear_session_removes_recorded_calls(fresh_module):
    ctx = fresh_module(eval_mocks=True)
    ctx.record_tool_call("sess-1", "list_transactions", {}, {})
    ctx.clear_session("sess-1")
    assert ctx.get_tool_calls("sess-1") == []
