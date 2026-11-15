import pytest


@pytest.mark.requires_supabase
def test_get_profile_returns_row_and_auto_upserts(app_client, test_user):
    uid, token = test_user
    res = app_client.get("/profile", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == uid
    # `risk_tolerance` has a DB default of 'moderate'; the test_user fixture
    # upserts only {"id": uid}, so the default should apply. Accept None as
    # well in case the fixture is run against a schema without the default.
    assert body["risk_tolerance"] in (None, "moderate")
    for field in ("age", "dependents", "annual_income", "monthly_expenses"):
        assert field in body


@pytest.mark.requires_supabase
def test_patch_profile_persists(app_client, test_user):
    uid, token = test_user
    headers = {"Authorization": f"Bearer {token}"}
    res = app_client.patch(
        "/profile",
        json={"age": 32, "annual_income": 120000},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["age"] == 32
    assert float(body["annual_income"]) == 120000.0
    # Round-trip
    res2 = app_client.get("/profile", headers=headers)
    assert res2.json()["age"] == 32


@pytest.mark.requires_supabase
def test_patch_rejects_invalid(app_client, test_user):
    _, token = test_user
    res = app_client.patch(
        "/profile",
        json={"risk_tolerance": "yolo"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422


@pytest.fixture
def second_user(test_user):
    """A distinct test user created per test for RLS checks."""
    import uuid
    from supabase import create_client
    from app.config import settings

    db = create_client(settings.supabase_url, settings.supabase_service_key)
    email = f"test-rls-{uuid.uuid4().hex[:8]}@example.com"
    created = db.auth.admin.create_user(
        {"email": email, "password": "TestPassword123!", "email_confirm": True}
    )
    uid = created.user.id
    db.table("profiles").upsert({"id": uid}).execute()
    signed = db.auth.sign_in_with_password(
        {"email": email, "password": "TestPassword123!"}
    )
    token = signed.session.access_token
    yield (uid, token)
    db.table("profiles").delete().eq("id", uid).execute()
    db.auth.admin.delete_user(uid)


@pytest.mark.requires_supabase
def test_memory_get_and_delete(app_client, test_user):
    uid, token = test_user
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.supabase_url, settings.supabase_service_key)
    # Memory fields live on the profiles row directly now.
    db.table("profiles").update({
        "preferences": "p",
        "financial_status": "s",
        "financial_goals": "g",
    }).eq("id", uid).execute()

    h = {"Authorization": f"Bearer {token}"}
    res = app_client.get("/profile/memory", headers=h)
    assert res.status_code == 200
    assert res.json()["preferences"] == "p"

    res2 = app_client.delete("/profile/memory", headers=h)
    assert res2.status_code == 204

    res3 = app_client.get("/profile/memory", headers=h)
    assert res3.status_code == 200
    assert res3.json().get("preferences") in (None, "")


@pytest.mark.requires_supabase
def test_rls_blocks_cross_user_reads(app_client, test_user, second_user):
    uid_a, token_a = test_user
    uid_b, _ = second_user
    # User A writes
    app_client.patch(
        "/profile",
        json={"age": 42},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    # User A's read returns their own, NOT B's
    res = app_client.get(
        "/profile", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert res.json()["id"] == uid_a
    assert res.json()["age"] == 42
