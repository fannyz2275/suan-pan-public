"""Unit tests for app.policy.router — uses FastAPI TestClient with the
auth dependency + db mocked. No live Supabase required."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.middleware import get_current_user
from app.main import app
from app.policy.schema import Domain, Override


class _U:
    def __init__(self, uid):
        self.id = uid
        self.email = "test@example.com"


@pytest.fixture
def auth_as():
    """Override the auth dep to act as a given user_id for this test."""
    def _set(uid: str):
        app.dependency_overrides[get_current_user] = lambda: _U(uid)
    yield _set
    app.dependency_overrides.pop(get_current_user, None)


def _override(*, user_id, key="description:starbucks", domain=Domain.CATEGORIZE,
              value=None, strength=2) -> Override:
    now = datetime.now(timezone.utc)
    return Override(
        id=uuid4(), user_id=user_id, domain=domain,
        key=key, value=value or {"category": "Food"},
        strength=strength,
        created_at=now, last_reinforced_at=now,
    )


# ---- GET /policy/me ---------------------------------------------------------


def test_get_me_returns_overrides_grouped_by_domain(auth_as):
    uid = uuid4()
    auth_as(str(uid))
    overrides = [
        _override(user_id=uid, key="description:starbucks",
                  domain=Domain.CATEGORIZE, value={"category": "Food"}),
        _override(user_id=uid, key="external:venmo cashout",
                  domain=Domain.TRANSFERS, value={"always_external": True}),
    ]
    with patch("app.policy.router.policy_store.list_for_user",
               return_value=overrides), \
         patch("app.policy.router._load_tool_priors", return_value=[]):
        with TestClient(app) as client:
            res = client.get("/policy/me")
    assert res.status_code == 200
    body = res.json()
    assert {o["domain"] for o in body["overrides"]} == {"categorize", "transfers"}
    assert body["tool_priors"] == []


def test_get_me_empty_returns_empty_lists(auth_as):
    auth_as(str(uuid4()))
    with patch("app.policy.router.policy_store.list_for_user", return_value=[]), \
         patch("app.policy.router._load_tool_priors", return_value=[]):
        with TestClient(app) as client:
            res = client.get("/policy/me")
    assert res.status_code == 200
    assert res.json() == {"overrides": [], "tool_priors": []}


# ---- _load_tool_priors -----------------------------------------------------


def test_load_tool_priors_caps_per_ctx_at_top_k():
    """Each ctx_signature group is capped at TOOL_PRIORS_TOP_K."""
    from app.policy.router import _load_tool_priors, TOOL_PRIORS_TOP_K

    db = MagicMock()
    rows = [
        {
            "tool_name": f"tool_{i}",
            "ctx_signature": "asking_about_spending",
            "success_count": i, "miss_count": 0,
            "utility_score": 0.9 - 0.01 * i,
            "last_used_at": "2026-05-01T00:00:00Z",
        }
        for i in range(TOOL_PRIORS_TOP_K + 4)
    ]
    db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = SimpleNamespace(
        data=rows,
    )

    out = _load_tool_priors(db, str(uuid4()))
    assert len(out) == TOOL_PRIORS_TOP_K


def test_load_tool_priors_swallows_missing_table():
    """Missing table (migration not yet applied) returns empty + 200, mimicking
    the no-data-yet path. Real DB failures must propagate so monitoring fires."""
    from app.policy.router import _load_tool_priors

    db = MagicMock()
    db.table.side_effect = RuntimeError("relation \"user_tool_priors\" does not exist")
    assert _load_tool_priors(db, str(uuid4())) == []


def test_load_tool_priors_propagates_real_db_failure():
    """Anything that isn't the missing-table case must propagate so the user
    sees a 500 and monitoring catches the outage instead of a silent empty."""
    from app.policy.router import _load_tool_priors

    db = MagicMock()
    db.table.side_effect = RuntimeError("connection refused")
    with pytest.raises(RuntimeError):
        _load_tool_priors(db, str(uuid4()))


def test_load_tool_priors_treats_missing_ctx_as_other():
    from app.policy.router import _load_tool_priors

    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = SimpleNamespace(
        data=[{
            "tool_name": "x", "ctx_signature": None,
            "success_count": 1, "miss_count": 0,
            "utility_score": 0.5, "last_used_at": None,
        }],
    )
    out = _load_tool_priors(db, str(uuid4()))
    assert out[0].ctx_signature == "other"


# ---- DELETE /policy/overrides/{id} -----------------------------------------


def test_delete_retires_owned_override(auth_as):
    uid = uuid4()
    auth_as(str(uid))
    override_id = uuid4()
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"user_id": str(uid)}],
    )

    with patch("app.policy.router._db", return_value=db), \
         patch("app.policy.router.policy_store.retire") as retire_call:
        with TestClient(app) as client:
            res = client.delete(f"/policy/overrides/{override_id}")
    assert res.status_code == 204
    retire_call.assert_called_once()


def test_delete_other_users_override_returns_404(auth_as):
    """Cross-user delete must look identical to 'not found' to avoid
    leaking the existence of other users' overrides."""
    auth_as(str(uuid4()))
    other_uid = uuid4()
    override_id = uuid4()
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{"user_id": str(other_uid)}],
    )

    with patch("app.policy.router._db", return_value=db), \
         patch("app.policy.router.policy_store.retire") as retire_call:
        with TestClient(app) as client:
            res = client.delete(f"/policy/overrides/{override_id}")
    assert res.status_code == 404
    retire_call.assert_not_called()


def test_delete_missing_override_returns_404(auth_as):
    auth_as(str(uuid4()))
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[],
    )

    with patch("app.policy.router._db", return_value=db):
        with TestClient(app) as client:
            res = client.delete(f"/policy/overrides/{uuid4()}")
    assert res.status_code == 404
