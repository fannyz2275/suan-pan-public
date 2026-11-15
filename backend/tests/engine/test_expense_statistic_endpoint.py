from unittest.mock import MagicMock, patch
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


def _mock_db(transactions):
    db = MagicMock()
    chain = db.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.execute.return_value = MagicMock(data=transactions)
    return db


def test_endpoint_returns_dict_for_authenticated_user():
    db = _mock_db([])
    client = TestClient(app)
    with patch("app.engine.router._db", return_value=db):
        res = client.get("/engine/expenses-statistic")
    assert res.status_code == 200
    body = res.json()
    assert "value" in body and "source" in body and "sample_size" in body and "window_days" in body
    assert body["window_days"] == 90


def test_endpoint_accepts_window_days_param():
    db = _mock_db([])
    client = TestClient(app)
    with patch("app.engine.router._db", return_value=db):
        res = client.get("/engine/expenses-statistic?window_days=30")
    assert res.status_code == 200
    assert res.json()["window_days"] == 30


def test_endpoint_requires_auth():
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    res = client.get("/engine/expenses-statistic")
    assert res.status_code in (401, 403)
