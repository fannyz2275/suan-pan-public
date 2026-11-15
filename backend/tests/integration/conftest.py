import logging
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv
from supabase import create_client as _create_client

# Load test env BEFORE app imports
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env.test"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH, override=True)
# Otherwise, fall back to the defaults from backend/tests/conftest.py so tests
# can skip gracefully without a test Supabase project set up.

from fastapi.testclient import TestClient

from app.main import app
from app.mcp import server as mcp_server
from tests.integration.mock_gemini import MockGeminiClient

_log = logging.getLogger(__name__)


def pytest_collection_modifyitems(config, items):
    """Skip tests marked `requires_supabase` if backend/.env.test is missing."""
    if _ENV_PATH.exists():
        return
    skip_marker = pytest.mark.skip(
        reason="backend/.env.test not set up; see .env.test.example"
    )
    for item in items:
        if "requires_supabase" in item.keywords:
            item.add_marker(skip_marker)


def _admin_db():
    from app.config import settings
    return _create_client(settings.supabase_url, settings.supabase_service_key)


@pytest.fixture
def test_user():
    """Creates an auth.users row via admin API, yields (user_id, access_token)."""
    db = _admin_db()
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPassword123!"
    created = db.auth.admin.create_user({"email": email, "password": password, "email_confirm": True})
    uid = created.user.id
    # Ensure profile row exists (handle_new_user trigger may not be installed yet)
    db.table("profiles").upsert({"id": uid}).execute()
    # Sign in to obtain a JWT
    signed = db.auth.sign_in_with_password({"email": email, "password": password})
    token = signed.session.access_token
    yield (uid, token)
    # Cleanup
    try:
        db.table("transactions").delete().eq("user_id", uid).execute()
        session_ids = [
            s["id"]
            for s in db.table("chat_sessions").select("id").eq("user_id", uid).execute().data
        ]
        if session_ids:
            db.table("chat_messages").delete().in_("session_id", session_ids).execute()
        db.table("chat_sessions").delete().eq("user_id", uid).execute()
        db.table("profiles").delete().eq("id", uid).execute()
        db.auth.admin.delete_user(uid)
    except Exception as exc:
        _log.warning("test_user cleanup failed for %s: %s", uid, exc)


@pytest.fixture
def seeded_transactions(test_user):
    """Inserts a deterministic 10-transaction set for the test user."""
    uid, _ = test_user
    db = _admin_db()
    rows = [
        {"user_id": uid, "date": "2025-11-03", "description": "Amazon",        "amount": -42.18,  "category": "Shopping", "account_id": None},
        {"user_id": uid, "date": "2025-11-10", "description": "Amazon Prime",  "amount": -139.00, "category": "Shopping", "account_id": None},
        {"user_id": uid, "date": "2025-12-03", "description": "Amazon",        "amount": -24.99,  "category": "Other",    "account_id": None},
        {"user_id": uid, "date": "2025-12-11", "description": "Amazon",        "amount": -67.50,  "category": "Other",    "account_id": None},
        {"user_id": uid, "date": "2025-12-20", "description": "Amazon",        "amount": -13.49,  "category": "Other",    "account_id": None},
        {"user_id": uid, "date": "2025-12-04", "description": "Whole Foods",   "amount": -87.20,  "category": "Food",     "account_id": None},
        {"user_id": uid, "date": "2025-12-11", "description": "Whole Foods",   "amount": -54.10,  "category": "Food",     "account_id": None},
        {"user_id": uid, "date": "2025-12-18", "description": "Whole Foods",   "amount": -110.00, "category": "Food",     "account_id": None},
        {"user_id": uid, "date": "2025-12-07", "description": "Zelle payment to John", "amount": -5000, "category": None, "account_id": None},
        {"user_id": uid, "date": "2025-12-15", "description": "Venmo to Sarah","amount": -300,    "category": None,       "account_id": None},
    ]
    db.table("transactions").insert(rows).execute()
    yield rows


class _InProcMCPSession:
    """Duck-typed MCP client session that dispatches to the real call_tool handler."""
    async def list_tools(self):
        tools = await mcp_server.list_tools()
        return SimpleNamespace(tools=tools)

    async def call_tool(self, name: str, arguments: dict):
        parts = await mcp_server.call_tool(name, arguments)
        return SimpleNamespace(content=parts)


@pytest.fixture
def mock_mcp_session():
    return _InProcMCPSession()


@pytest.fixture
def mock_gemini(monkeypatch):
    client = MockGeminiClient()
    import app.advisor.router as advisor_router
    monkeypatch.setattr(advisor_router, "_gemini", lambda: client)
    return client


@pytest.fixture
def app_client(mock_mcp_session, mock_gemini):
    """TestClient with MCP + Gemini mocks wired in."""
    # Preset sentinel attrs so lifespan teardown never raises AttributeError,
    # even if startup failed partway through.
    app.state._mcp_session_ctx = getattr(app.state, "_mcp_session_ctx", None)
    app.state._mcp_stdio_ctx = getattr(app.state, "_mcp_stdio_ctx", None)
    app.state.mcp_session = mock_mcp_session
    with TestClient(app) as c:
        yield c
    app.state.mcp_session = None
