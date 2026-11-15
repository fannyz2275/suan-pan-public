"""Integration tests for the /notes router."""
from __future__ import annotations

import os
import asyncio

import pytest
from fastapi.testclient import TestClient


def _has_supabase_config() -> bool:
    return bool(os.environ.get("SUPABASE_URL")) and bool(os.environ.get("SUPABASE_SERVICE_KEY"))


@pytest.mark.integration
def test_post_feedback_creates_example_notes(test_user, supabase_admin_db):
    if not _has_supabase_config():
        pytest.skip("Supabase not configured")

    uid, _ = test_user

    from app.auth.middleware import get_current_user
    from app.main import app

    class _U:
        def __init__(self, _uid):
            self.id = _uid
            self.email = "test@example.com"

    app.dependency_overrides[get_current_user] = lambda: _U(uid)
    try:
        # Seed a chat session + user msg + assistant msg
        sess = supabase_admin_db.table("chat_sessions").insert({
            "user_id": str(uid), "kind": "general",
        }).execute().data[0]
        user_msg = supabase_admin_db.table("chat_messages").insert({
            "session_id": sess["id"], "role": "user", "content": "How are my goals?",
        }).execute().data[0]
        asst_msg = supabase_admin_db.table("chat_messages").insert({
            "session_id": sess["id"], "role": "assistant", "content": "Here are your goals: ...",
        }).execute().data[0]

        with TestClient(app) as client:
            res = client.post(
                "/notes/feedback",
                json={
                    "message_id": asst_msg["id"],
                    "labels": {
                        "good_advice": True,
                        "accurate_numbers": True,
                        "on_topic": False,
                        "off_topic": False,
                        "bad_advice": False,
                        "inaccurate_numbers": False,
                    },
                },
            )
        assert res.status_code == 200, res.text

        rows = (
            supabase_admin_db.table("user_notes").select("*")
            .eq("user_id", str(uid))
            .eq("source", "message_feedback").execute().data
        )
        labels = {(r.get("provenance") or {}).get("label") for r in rows}
        assert "good_advice" in labels
        assert "accurate_numbers" in labels

        # Cleanup chat rows (test_user fixture cleans user_notes)
        supabase_admin_db.table("chat_messages").delete().eq("session_id", sess["id"]).execute()
        supabase_admin_db.table("chat_sessions").delete().eq("id", sess["id"]).execute()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
def test_get_notes_returns_users_live_notes_when_flag_enabled(test_user, supabase_admin_db, monkeypatch):
    if not _has_supabase_config():
        pytest.skip("Supabase not configured")

    uid, _ = test_user
    monkeypatch.setenv("NOTES_DEBUG_API", "1")

    from app.auth.middleware import get_current_user
    from app.main import app

    class _U:
        def __init__(self, _uid):
            self.id = _uid
            self.email = "test@example.com"

    app.dependency_overrides[get_current_user] = lambda: _U(uid)
    try:
        supabase_admin_db.table("user_notes").insert({
            "user_id": str(uid), "kind": "preference",
            "content": "test pref",
            "source": "chat_extraction",
        }).execute()

        with TestClient(app) as client:
            res = client.get("/notes")
        assert res.status_code == 200, res.text
        body = res.json()
        assert any(n["content"] == "test pref" for n in body["notes"])
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
def test_get_notes_404_when_flag_disabled(test_user, monkeypatch):
    if not _has_supabase_config():
        pytest.skip("Supabase not configured")

    uid, _ = test_user
    monkeypatch.delenv("NOTES_DEBUG_API", raising=False)

    from app.auth.middleware import get_current_user
    from app.main import app

    class _U:
        def __init__(self, _uid):
            self.id = _uid

    app.dependency_overrides[get_current_user] = lambda: _U(uid)
    try:
        with TestClient(app) as client:
            res = client.get("/notes")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
def test_post_extract_now_runs_extractor(test_user, monkeypatch):
    if not _has_supabase_config():
        pytest.skip("Supabase not configured")

    uid, _ = test_user
    called = {"v": False}

    async def fake_extract(*, db, gemini, user_id):
        called["v"] = True
        return 1

    monkeypatch.setattr("app.notes.router.extract_for_user", fake_extract)

    from app.auth.middleware import get_current_user
    from app.main import app

    class _U:
        def __init__(self, _uid):
            self.id = _uid

    app.dependency_overrides[get_current_user] = lambda: _U(uid)
    try:
        with TestClient(app) as client:
            res = client.post("/notes/extract-now")
        assert res.status_code == 200, res.text
        assert called["v"] is True
        assert res.json()["inserted"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
