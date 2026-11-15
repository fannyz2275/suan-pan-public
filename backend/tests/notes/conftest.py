"""Fixtures for notes integration tests.

Loads backend/.env.test (if present) and provides a supabase_admin_db
fixture backed by a real Supabase service-role client, plus a test_user
fixture that creates and tears down a real auth.users row.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv

_log = logging.getLogger(__name__)

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env.test"
_FALLBACK_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH, override=True)
elif _FALLBACK_ENV_PATH.exists():
    load_dotenv(_FALLBACK_ENV_PATH, override=True)

_HAS_SUPABASE_CONFIG = _ENV_PATH.exists() or _FALLBACK_ENV_PATH.exists()


def pytest_collection_modifyitems(config, items):
    """Skip tests marked `integration` if no Supabase config is available."""
    if _HAS_SUPABASE_CONFIG:
        return
    skip_marker = pytest.mark.skip(
        reason="No backend/.env.test or .env found; Supabase not configured"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture
def supabase_admin_db():
    """Function-scoped Supabase admin client.

    Function-scoped so each test gets a clean auth context — the supabase-py
    client mutates its own auth state on `auth.sign_in_with_password`, which
    would corrupt service-role calls for any subsequent test sharing the client.
    """
    from app.config import settings
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)


@pytest.fixture
def test_user(supabase_admin_db):
    """Creates a real auth.users row, yields (user_id, None), then cleans up.

    Does NOT sign in — sign_in_with_password mutates the client's auth state and
    causes subsequent service-role table calls to go through the user's JWT (and
    hit RLS). The token slot is kept for backward-compatible unpacking; pass a
    real client through if you need an authenticated client in some future test.
    """
    db = supabase_admin_db
    email = f"test-notes-{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPassword123!"
    created = db.auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    uid = created.user.id
    # Ensure profile row exists (handle_new_user trigger may not be installed)
    try:
        db.table("profiles").upsert({"id": uid}).execute()
    except Exception:
        pass
    yield (uid, None)
    # Cleanup
    try:
        db.table("user_notes").delete().eq("user_id", uid).execute()
    except Exception as exc:
        _log.warning("user_notes cleanup failed for %s: %s", uid, exc)
    try:
        db.table("profiles").delete().eq("id", uid).execute()
    except Exception:
        pass
    try:
        db.auth.admin.delete_user(uid)
    except Exception as exc:
        _log.warning("auth user cleanup failed for %s: %s", uid, exc)
