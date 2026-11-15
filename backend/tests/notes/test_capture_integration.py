"""End-to-end test for emit_fact_from_edit wiring.

Exercises PATCH /finance/accounts/{id} against a real Supabase test project
and verifies a corresponding fact note appears in user_notes.
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest
from fastapi.testclient import TestClient


def _has_supabase_config() -> bool:
    return bool(os.environ.get("SUPABASE_URL")) and bool(
        os.environ.get("SUPABASE_SERVICE_KEY")
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_account_rename_creates_fact_note(test_user, supabase_admin_db):
    """End-to-end: PATCH an account, verify a user_notes fact row appears."""
    if not _has_supabase_config():
        pytest.skip("Supabase not configured")

    uid, _ = test_user

    # Auth override — the notes-conftest test_user fixture intentionally does
    # not sign the user in (the supabase-py client mutates auth state per-call,
    # which would break service-role operations). Instead, override the auth
    # dependency directly.
    from app.auth.middleware import get_current_user
    from app.main import app

    class _U:
        def __init__(self, _uid):
            self.id = _uid
            self.email = "test@example.com"

    app.dependency_overrides[get_current_user] = lambda: _U(uid)

    try:
        with TestClient(app) as client:
            create = client.post(
                "/finance/accounts",
                json={
                    "name": "Old Name",
                    "type": "checking",
                    "balance": 1000,
                    "is_active": True,
                },
            )
            assert create.status_code in (200, 201), create.text
            account_id = create.json()["id"]

            patch = client.patch(
                f"/finance/accounts/{account_id}",
                json={
                    "name": "Emergency Cash",
                    "type": "checking",
                    "balance": 1000,
                    "is_active": True,
                },
            )
            assert patch.status_code == 200, patch.text

        # Best-effort emit may include an LLM call — give it a brief grace period.
        deadline = time.time() + 15
        rows: list[dict] = []
        while time.time() < deadline:
            rows = (
                supabase_admin_db.table("user_notes")
                .select("*")
                .eq("user_id", str(uid))
                .eq("kind", "fact")
                .contains("tags", [f"entity:account:{account_id}"])
                .execute()
                .data
                or []
            )
            if rows:
                break
            await asyncio.sleep(0.5)

        assert len(rows) >= 1, (
            f"no fact note created. user_notes rows for user: {rows}"
        )
        name_facts = [
            r for r in rows if (r.get("provenance") or {}).get("field") == "name"
        ]
        assert len(name_facts) >= 1, (
            f"expected a name-field fact, got: {[r.get('provenance') for r in rows]}"
        )

        # Cleanup the account row to keep the test DB tidy.
        try:
            supabase_admin_db.table("accounts").delete().eq("id", account_id).execute()
        except Exception:
            pass
    finally:
        app.dependency_overrides.pop(get_current_user, None)
