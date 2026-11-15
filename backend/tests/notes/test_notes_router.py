"""Unit tests for GET /notes/user and DELETE /notes/user/{id} endpoints."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


class _User:
    def __init__(self, uid):
        self.id = uid
        self.email = "u@test.example.com"


def _override_auth(uid):
    from app.auth.middleware import get_current_user
    app.dependency_overrides[get_current_user] = lambda: _User(uid)


def _clear_overrides():
    app.dependency_overrides.clear()


def _make_note_row(
    *,
    user_id,
    note_id=None,
    kind="fact",
    content="test content",
    expires_at=None,
    superseded_by=None,
    importance=7,
    strength=2,
    created_at="2024-01-01T00:00:00+00:00",
):
    return {
        "id": str(note_id or uuid4()),
        "user_id": str(user_id),
        "kind": kind,
        "content": content,
        "tags": ["budget"],
        "entity_refs": {},
        "embedding": None,
        "source": "chat_extraction",
        "provenance": {},
        "strength": strength,
        "importance": importance,
        "last_accessed_at": None,
        "supersedes": [],
        "superseded_by": superseded_by,
        "expires_at": expires_at,
        "created_at": created_at,
    }


def test_list_notes_returns_non_expired():
    """GET /notes/user returns the non-expired fact note and excludes nothing."""
    uid = uuid4()
    note_id = uuid4()
    row = _make_note_row(user_id=uid, note_id=note_id, kind="fact", expires_at=None)

    mock_db = MagicMock()
    # Chain: .table().select().eq().in_().is_().order().execute()
    mock_db.table.return_value.select.return_value.eq.return_value \
        .in_.return_value.is_.return_value.order.return_value \
        .execute.return_value.data = [row]

    _override_auth(uid)
    try:
        from app.db import get_admin_db as _db
        app.dependency_overrides[_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.get("/notes/user")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["id"] == str(note_id)
        assert body[0]["kind"] == "fact"
        assert body[0]["content"] == "test content"
        assert body[0]["importance"] == 7
        assert body[0]["strength"] == 2
    finally:
        _clear_overrides()


def test_list_notes_excludes_expired():
    """GET /notes/user filters out rows where expires_at is in the past."""
    uid = uuid4()
    # expires_at is in the past → _is_expired returns True
    past = "2000-01-01T00:00:00+00:00"
    row = _make_note_row(user_id=uid, kind="preference", expires_at=past)

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value \
        .in_.return_value.is_.return_value.order.return_value \
        .execute.return_value.data = [row]

    _override_auth(uid)
    try:
        from app.db import get_admin_db as _db
        app.dependency_overrides[_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.get("/notes/user")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == []
    finally:
        _clear_overrides()


def test_delete_note_calls_retire():
    """DELETE /notes/user/{id} calls retire_note and returns 204 when found."""
    uid = uuid4()
    note_id = uuid4()
    row = {"id": str(note_id), "user_id": str(uid), "expires_at": None}

    mock_db = MagicMock()
    # Chain: .table().select().eq().eq().limit().execute()
    mock_db.table.return_value.select.return_value.eq.return_value \
        .eq.return_value.limit.return_value.execute.return_value.data = [row]

    _override_auth(uid)
    try:
        from app.db import get_admin_db as _db
        app.dependency_overrides[_db] = lambda: mock_db

        with patch("app.notes.router.retire_note") as mock_retire:
            client = TestClient(app)
            resp = client.delete(f"/notes/user/{note_id}")
            assert resp.status_code == 204, resp.text
            mock_retire.assert_called_once_with(mock_db, note_id)
    finally:
        _clear_overrides()


def test_delete_note_returns_404_when_not_found():
    """DELETE /notes/user/{id} returns 404 if no matching note is found for this user."""
    uid = uuid4()
    note_id = uuid4()

    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value \
        .eq.return_value.limit.return_value.execute.return_value.data = []

    _override_auth(uid)
    try:
        from app.db import get_admin_db as _db
        app.dependency_overrides[_db] = lambda: mock_db

        client = TestClient(app)
        resp = client.delete(f"/notes/user/{note_id}")
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "Note not found"
    finally:
        _clear_overrides()
