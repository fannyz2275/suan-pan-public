"""Tests for eval-mode auth bypass in app.auth.middleware."""
import importlib
import os

import pytest
from fastapi import FastAPI, Depends
from starlette.testclient import TestClient


def _build_app():
    """Re-import middleware so EVAL_MOCKS_ENABLED reflects current env."""
    from app.auth import middleware
    importlib.reload(middleware)
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user=Depends(middleware.get_current_user)):
        return {"id": user.id, "email": user.email}

    return app


def test_bypass_active_when_eval_mocks_set_and_header_present(monkeypatch):
    monkeypatch.setenv("EVAL_MOCKS", "1")
    app = _build_app()
    client = TestClient(app)
    r = client.get(
        "/whoami",
        headers={"X-Eval-User-Id": "u-eval-c", "Authorization": "Bearer ignored"},
    )
    assert r.status_code == 200
    assert r.json() == {"id": "u-eval-c", "email": "u-eval-c@suan-pan.eval"}


def test_bypass_inert_when_eval_mocks_unset(monkeypatch):
    monkeypatch.delenv("EVAL_MOCKS", raising=False)
    app = _build_app()
    client = TestClient(app)
    r = client.get(
        "/whoami",
        headers={"X-Eval-User-Id": "u-eval-c", "Authorization": "Bearer not-a-real-jwt"},
    )
    assert r.status_code == 401


def test_bypass_inert_when_header_missing_even_with_eval_mocks(monkeypatch):
    monkeypatch.setenv("EVAL_MOCKS", "1")
    app = _build_app()
    client = TestClient(app)
    r = client.get("/whoami", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert r.status_code == 401


def test_module_import_warns_when_eval_mocks_enabled(monkeypatch, caplog):
    monkeypatch.setenv("EVAL_MOCKS", "1")
    import logging
    with caplog.at_level(logging.WARNING, logger="app.auth.middleware"):
        _build_app()
    assert any("EVAL_MOCKS=1 detected at startup" in r.message for r in caplog.records)
