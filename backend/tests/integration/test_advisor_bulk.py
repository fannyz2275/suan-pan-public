import pytest


@pytest.mark.requires_supabase
def test_bulk_recategorize_rejected_without_preview(app_client, test_user, seeded_transactions, mock_gemini):
    from tests.integration.mock_gemini import ChunkToolCall, ChunkText
    _, token = test_user

    # Round 1: model calls dry_run=false without any preview — should be rejected
    mock_gemini.enqueue([ChunkToolCall("bulk_recategorize", {
        "description_pattern": "Amazon", "date_from": "2025-01-01", "date_to": "2025-12-31",
        "new_category": "Shopping", "dry_run": False,
    })])
    # Round 2: model narrates after error
    mock_gemini.enqueue([ChunkText("Let me preview first.")])

    res = app_client.post("/advisor/chat", headers={"Authorization": f"Bearer {token}"},
                          json={"message": "Recategorize Amazon as Shopping"})
    body = res.content.decode()
    assert "destructive_call_not_previewed" in body


@pytest.mark.requires_supabase
def test_bulk_recategorize_happy_path(app_client, test_user, seeded_transactions, mock_gemini):
    from tests.integration.mock_gemini import ChunkToolCall, ChunkText
    from supabase import create_client
    from app.config import settings
    uid, token = test_user

    same_args = {"description_pattern": "Amazon", "date_from": "2025-01-01", "date_to": "2025-12-31",
                 "new_category": "Shopping"}
    # Turn 1: dry_run=true
    mock_gemini.enqueue([ChunkToolCall("bulk_recategorize", {**same_args, "dry_run": True})])
    # Turn 1 continuation: narrate preview
    mock_gemini.enqueue([ChunkText("I found 5 matches. Ready to apply?")])
    # Turn 2 (user confirms) round 1: dry_run=false
    mock_gemini.enqueue([ChunkToolCall("bulk_recategorize", {**same_args, "dry_run": False})])
    # Turn 2 round 2: narrate success
    mock_gemini.enqueue([ChunkText("Done. Recategorized 5 Amazon transactions as Shopping.")])

    h = {"Authorization": f"Bearer {token}"}
    res1 = app_client.post("/advisor/chat", headers=h, json={"message": "Reclassify Amazon as Shopping"})
    sess_id = None
    for line in res1.content.decode().split("\n"):
        if '"session_id"' in line:
            import json as _j
            sess_id = _j.loads(line.split("data: ", 1)[-1]).get("session_id")
    assert sess_id

    res2 = app_client.post("/advisor/chat", headers=h,
                           json={"message": "Confirmed: apply the recategorization.", "session_id": sess_id})
    body2 = res2.content.decode()
    assert "Done" in body2
    # Guardrail must have cleared on the confirmed turn — if this string
    # appears, the destructive call was (incorrectly) rejected.
    assert "destructive_call_not_previewed" not in body2

    db = create_client(settings.supabase_url, settings.supabase_service_key)
    rows = db.table("transactions").select("description,category").eq("user_id", uid).execute().data
    amazon = [r for r in rows if "Amazon" in r["description"]]
    assert all(r["category"] == "Shopping" for r in amazon)
