"""Tests for /eval/* endpoints."""
import importlib

import pytest
from starlette.testclient import TestClient


def _client_with_eval_mocks(monkeypatch, enabled: bool):
    if enabled:
        monkeypatch.setenv("EVAL_MOCKS", "1")
    else:
        monkeypatch.delenv("EVAL_MOCKS", raising=False)
    # Reload main and middleware so module-level env reads take effect.
    from app.auth import middleware
    importlib.reload(middleware)
    from app import main
    importlib.reload(main)
    return TestClient(main.app)


def test_tool_calls_endpoint_returns_recorded(monkeypatch):
    client = _client_with_eval_mocks(monkeypatch, enabled=True)
    from app.eval import context as ctx
    importlib.reload(ctx)
    ctx.record_tool_call("sess-7", "list_transactions",
                         {"date_from": "2026-04-01"}, {"rows": []})
    r = client.get("/eval/tool_calls/sess-7")
    assert r.status_code == 200
    assert r.json() == [
        {"name": "list_transactions",
         "args": {"date_from": "2026-04-01"},
         "result_data": {"rows": []}},
    ]


def test_tool_calls_endpoint_empty_for_unknown_session(monkeypatch):
    client = _client_with_eval_mocks(monkeypatch, enabled=True)
    r = client.get("/eval/tool_calls/never-seen")
    assert r.status_code == 200
    assert r.json() == []


def test_tool_calls_endpoint_404_when_eval_mocks_unset(monkeypatch):
    client = _client_with_eval_mocks(monkeypatch, enabled=False)
    r = client.get("/eval/tool_calls/sess-1")
    assert r.status_code == 404
