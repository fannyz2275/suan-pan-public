"""Integration test: advisor preserves partial response on mid-stream error."""
import json
import pytest
from tests.integration.mock_gemini import ChunkText


@pytest.mark.requires_supabase
def test_mid_stream_error_preserves_partial_text(app_client, test_user, mock_gemini):
    _, token = test_user

    async def _failing_gen():
        yield ChunkText("Here's what I found: ")
        raise RuntimeError("simulated upstream error")

    class _Models:
        async def generate_content_stream(self, *, model, contents, config):
            return _failing_gen()

    mock_gemini.aio.models = _Models()

    res = app_client.post(
        "/advisor/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Show me transactions"},
    )
    body = res.content.decode()
    # Both the partial text AND the error note should appear in the streamed events
    assert "Here's what I found:" in body
    assert "error" in body.lower()


@pytest.mark.requires_supabase
def test_tool_hang_yields_tool_timeout(app_client, test_user, mock_gemini, monkeypatch):
    from tests.integration.mock_gemini import ChunkToolCall, ChunkText
    import asyncio as _asyncio

    _, token = test_user
    # Round 1: model calls a tool; round 2: model narrates after seeing tool_timeout
    mock_gemini.enqueue([ChunkToolCall("get_transactions", {"date_from": "2025-12-01", "date_to": "2025-12-31"})])
    mock_gemini.enqueue([ChunkText("The lookup timed out — please try a narrower range.")])

    # Override the mcp session call_tool to hang
    from app.advisor import router as ar
    original_session = app_client.app.state.mcp_session

    class _Hang:
        async def list_tools(self):
            return await original_session.list_tools()

        async def call_tool(self, name, args):
            await _asyncio.sleep(10)  # longer than test timeout

    app_client.app.state.mcp_session = _Hang()

    # Reduce the tool timeout to 0.5s for this test
    monkeypatch.setattr(ar, "TOOL_CALL_TIMEOUT", 0.5)

    res = app_client.post("/advisor/chat", headers={"Authorization": f"Bearer {token}"},
                          json={"message": "show txns"})
    body = res.content.decode()
    assert "tool_timeout" in body or "timed out" in body


@pytest.mark.requires_supabase
def test_gemini_429_retries_then_succeeds(app_client, test_user, mock_gemini):
    from tests.integration.mock_gemini import ChunkText
    from app.advisor.resilience import TransientError

    _, token = test_user
    attempts = [0]

    class _Models:
        async def generate_content_stream(self, *, model, contents, config):
            attempts[0] += 1
            if attempts[0] == 1:
                raise TransientError("429 rate limited")

            async def _g():
                yield ChunkText("Recovered response")
            return _g()

    mock_gemini.aio.models = _Models()

    res = app_client.post("/advisor/chat", headers={"Authorization": f"Bearer {token}"},
                          json={"message": "hi"})
    assert "Recovered response" in res.content.decode()
    assert attempts[0] == 2


@pytest.mark.requires_supabase
def test_empty_response_persists_fallback(app_client, test_user, mock_gemini):
    _, token = test_user
    mock_gemini.enqueue([])  # zero chunks, no tool calls
    res = app_client.post("/advisor/chat", headers={"Authorization": f"Bearer {token}"},
                          json={"message": "hi"})
    assert "rephrasing" in res.content.decode().lower()


@pytest.mark.requires_supabase
def test_max_turns_reached_persists_fallback(app_client, test_user, mock_gemini):
    from tests.integration.mock_gemini import ChunkToolCall
    _, token = test_user
    # Force 10 rounds of tool calls with no text
    for _ in range(11):
        mock_gemini.enqueue([ChunkToolCall("get_transactions", {"date_from": "2025-12-01", "date_to": "2025-12-31"})])
    res = app_client.post("/advisor/chat", headers={"Authorization": f"Bearer {token}"},
                          json={"message": "loop forever"})
    assert "narrowing" in res.content.decode().lower()


@pytest.mark.requires_supabase
def test_heartbeat_emitted_during_tool_call(app_client, test_user, mock_gemini, monkeypatch):
    import asyncio as _asyncio
    from tests.integration.mock_gemini import ChunkToolCall, ChunkText
    _, token = test_user

    mock_gemini.enqueue([ChunkToolCall("get_transactions", {"date_from": "2025-12-01", "date_to": "2025-12-31"})])
    mock_gemini.enqueue([ChunkText("done")])

    original_session = app_client.app.state.mcp_session

    class _Slow:
        async def list_tools(self):
            return await original_session.list_tools()

        async def call_tool(self, name, args):
            await _asyncio.sleep(1.5)
            return await original_session.call_tool(name, args)

    app_client.app.state.mcp_session = _Slow()

    from app.advisor import router as ar
    monkeypatch.setattr(ar, "HEARTBEAT_INTERVAL", 0.4)

    res = app_client.post("/advisor/chat", headers={"Authorization": f"Bearer {token}"},
                          json={"message": "slow"})
    assert b": keepalive" in res.content


@pytest.mark.requires_supabase
def test_client_disconnect_persists_partial(app_client, test_user, mock_gemini):
    from tests.integration.mock_gemini import ChunkText
    from supabase import create_client
    from app.config import settings
    uid, token = test_user
    # Pre-enqueue a long response
    long_text = "partial response "
    mock_gemini.enqueue([ChunkText(long_text)])

    # Use a streamed request that aborts mid-way
    with app_client.stream("POST", "/advisor/chat",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"message": "disconnect"}) as resp:
        for chunk in resp.iter_raw():
            if long_text.encode() in chunk:
                break  # abort the stream

    # DB should have the partial text persisted with client_disconnect warning
    db = create_client(settings.supabase_url, settings.supabase_service_key)
    sessions = db.table("chat_sessions").select("id").eq("user_id", uid).execute().data
    assert sessions
    msgs = db.table("chat_messages").select("content,tool_context,role").eq("session_id", sessions[0]["id"]).execute().data
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert any(long_text.strip() in (m["content"] or "") for m in assistant)
    # Also verify tool_context records the client_disconnect warning
    assert any(
        "client_disconnect" in json.dumps(m.get("tool_context") or {})
        for m in assistant
    )
