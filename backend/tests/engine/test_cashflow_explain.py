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


def _valid_body():
    return {
        "projection": [{"month": "2026-05", "balance": 8500.0}],
        "history":    [{"month": "2026-04", "balance": 8200.0}],
        "starting_balance": 8200.0,
        "monthly_income": 6000.0,
        "monthly_expenses": 4500.0,
        "vesting_events": [],
        "fixed_recurring": {"inflow": 1200.0, "outflow": 350.0},
    }


def test_cashflow_explain_returns_explanation_string():
    fake_response = MagicMock()
    fake_response.text = "Your $8.2k starting cash..."
    fake_models = MagicMock()
    fake_models.generate_content.return_value = fake_response
    fake_client = MagicMock()
    fake_client.models = fake_models

    client = TestClient(app)
    with patch("app.engine.router._gemini_client", return_value=fake_client):
        res = client.post("/engine/cashflow-explain", json=_valid_body())
    assert res.status_code == 200
    assert res.json() == {"explanation": "Your $8.2k starting cash..."}
    fake_models.generate_content.assert_called_once()


def test_cashflow_explain_requires_auth():
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    res = client.post("/engine/cashflow-explain", json=_valid_body())
    assert res.status_code in (401, 403)


def test_cashflow_explain_rejects_missing_body_fields():
    client = TestClient(app)
    res = client.post("/engine/cashflow-explain", json={"projection": []})
    assert res.status_code == 422
