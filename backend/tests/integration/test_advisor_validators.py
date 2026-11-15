"""Integration tests for advisor in-flight validators (number/PII/actions)."""
import pytest

from tests.integration.mock_gemini import ChunkText, ChunkToolCall


@pytest.mark.requires_supabase
def test_pii_redacted_in_response(app_client, test_user, mock_gemini):
    _, token = test_user
    mock_gemini.enqueue([ChunkText("Your SSN is 123-45-6789 on file.")])
    res = app_client.post(
        "/advisor/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "debug"},
    )
    body = res.content.decode()
    assert "123-45-6789" not in body
    assert "[REDACTED]" in body


@pytest.mark.requires_supabase
def test_number_mismatch_logged_as_warning(
    app_client, test_user, seeded_transactions, mock_gemini
):
    uid, token = test_user
    mock_gemini.enqueue([
        ChunkToolCall(
            "get_spending_by_category",
            {"date_from": "2025-12-01", "date_to": "2025-12-31"},
        )
    ])
    # actual seeded food: 251.30 — mismatch
    mock_gemini.enqueue([ChunkText("You spent $1,500 on Food this month.")])
    app_client.post(
        "/advisor/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "how much food"},
    )
    from supabase import create_client
    from app.config import settings

    db = create_client(settings.supabase_url, settings.supabase_service_key)
    sess = db.table("chat_sessions").select("id").eq("user_id", uid).execute().data
    msgs = (
        db.table("chat_messages")
        .select("tool_context,role")
        .eq("session_id", sess[0]["id"])
        .execute()
        .data
    )
    asst = [m for m in msgs if m["role"] == "assistant"]
    assert any((m["tool_context"] or {}).get("validation_warnings") for m in asst)
