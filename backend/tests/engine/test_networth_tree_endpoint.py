from unittest.mock import MagicMock, patch, call
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth.middleware import get_current_user


USER_ID = str(uuid4())


class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.email = "u@example.com"


@pytest.fixture(autouse=True)
def patch_auth():
    app.dependency_overrides[get_current_user] = lambda: FakeUser(USER_ID)
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _mock_db(accounts):
    db = MagicMock()
    chain = db.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.execute.return_value = MagicMock(data=accounts)
    return db


def test_networth_tree_endpoint_returns_tree_for_user_accounts():
    accounts = [
        {"id": "a1", "type": "checking", "name": "Chase",
         "balance": 1000, "account_number_last4": "1234"},
        {"id": "a2", "type": "debt", "name": "Card",
         "balance": -200, "account_number_last4": "5678"},
    ]
    db = _mock_db(accounts)
    client = TestClient(app)
    with patch("app.engine.router._db", return_value=db):
        res = client.get("/engine/networth-tree")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "root"
    assert body["signed_value"] == 800
    # filter chain: user_id eq + is_active eq
    chain = db.table.return_value
    # Both filters must be present in the chain — defensive against a
    # regression that drops or rewrites the user_id filter.
    eq_calls = chain.eq.call_args_list
    assert call("user_id", USER_ID) in eq_calls
    assert call("is_active", True) in eq_calls


def test_networth_tree_endpoint_returns_empty_root_for_no_accounts():
    db = _mock_db([])
    client = TestClient(app)
    with patch("app.engine.router._db", return_value=db):
        res = client.get("/engine/networth-tree")
    assert res.status_code == 200
    body = res.json()
    assert body["value"] == 0
    assert body["signed_value"] == 0
    assert [c["id"] for c in body["children"]] == [
        "liquid", "investments", "non_current", "liabilities",
    ]


def test_networth_tree_endpoint_requires_auth():
    # Remove the auth override so the real dependency runs and returns 401.
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    res = client.get("/engine/networth-tree")
    assert res.status_code in (401, 403)
