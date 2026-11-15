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


def _mock_db(*, accounts=None, transactions=None):
    db = MagicMock()
    def make_chain(table_name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.lt.return_value = chain
        chain.order.return_value = chain
        if table_name == "accounts":
            chain.execute.return_value = MagicMock(data=accounts or [])
        elif table_name == "transactions":
            chain.execute.return_value = MagicMock(data=transactions or [])
        else:
            chain.execute.return_value = MagicMock(data=[])
        return chain
    db.table.side_effect = make_chain
    return db


def test_cashflow_history_returns_12_months_for_user_with_transactions():
    accounts = [{"id": "a1", "type": "checking", "balance": 10000}]
    transactions = [
        {"date": "2026-03-15", "amount": 5000, "user_id": USER_ID},
    ]
    db = _mock_db(accounts=accounts, transactions=transactions)
    client = TestClient(app)
    with patch("app.engine.router._db", return_value=db):
        res = client.get("/engine/cashflow-history?months=12")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 12
    assert all("month" in r and "balance" in r and "net" in r for r in body)


def test_cashflow_history_returns_zero_nets_for_user_with_no_transactions():
    accounts = [{"id": "a1", "type": "checking", "balance": 5000}]
    db = _mock_db(accounts=accounts, transactions=[])
    client = TestClient(app)
    with patch("app.engine.router._db", return_value=db):
        res = client.get("/engine/cashflow-history?months=6")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 6
    assert all(r["net"] == 0 for r in body)


def test_cashflow_history_requires_auth():
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    res = client.get("/engine/cashflow-history")
    assert res.status_code in (401, 403)
