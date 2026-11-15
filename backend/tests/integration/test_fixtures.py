import pytest
from supabase import create_client
from app.config import settings


@pytest.mark.requires_supabase
@pytest.mark.asyncio
async def test_test_user_fixture_creates_profile_row(test_user):
    uid, token = test_user
    db = create_client(settings.supabase_url, settings.supabase_service_key)
    rows = db.table("profiles").select("id").eq("id", uid).execute().data
    assert len(rows) == 1


@pytest.mark.requires_supabase
def test_seeded_transactions_has_expected_categories(seeded_transactions, test_user):
    uid, _ = test_user
    db = create_client(settings.supabase_url, settings.supabase_service_key)
    rows = db.table("transactions").select("description,amount,category").eq("user_id", uid).execute().data
    descs = {r["description"] for r in rows}
    assert "Amazon" in descs
    assert "Whole Foods" in descs
    assert "Zelle payment to John" in descs
    assert any(r["amount"] == -5000 for r in rows)
