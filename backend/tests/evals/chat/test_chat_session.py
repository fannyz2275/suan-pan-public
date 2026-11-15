"""Tests for ChatSession SSE client."""
from unittest.mock import MagicMock, patch

import pytest


SSE_LINES = [
    "data: {\"session_id\": \"sess-abc\"}",
    "data: {\"text\": \"Your portfolio \"}",
    "data: {\"text\": \"gained $1,200.\"}",
    "data: {\"tool_call\": \"portfolio_get_attribution\", \"status\": \"running\"}",
    "data: {\"tool_call\": \"portfolio_get_attribution\", \"status\": \"done\"}",
    "",
]


def _fake_stream():
    """Return a context manager that yields the canned SSE lines."""
    cm = MagicMock()
    response = MagicMock()
    response.iter_lines.return_value = iter(SSE_LINES)
    response.raise_for_status.return_value = None
    cm.__enter__.return_value = response
    cm.__exit__.return_value = False
    return cm


def test_send_accumulates_text_and_session_id():
    from tests.evals.chat.chat_session import ChatSession

    session = ChatSession(base_url="http://test", user_id="u-eval-c")
    with patch.object(session._client, "stream", return_value=_fake_stream()), \
         patch.object(session._client, "get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [
            {"name": "portfolio_get_attribution", "args": {}, "result_data": {"market": 1200}},
        ]
        reply, tool_calls = session.send({"role": "user", "content": "Why did it move?"})
    assert reply == "Your portfolio gained $1,200."
    assert session._session_id == "sess-abc"
    assert tool_calls == [
        {"name": "portfolio_get_attribution", "args": {},
         "result_data": {"market": 1200}},
    ]


def test_send_carries_session_id_on_subsequent_messages():
    from tests.evals.chat.chat_session import ChatSession

    session = ChatSession(base_url="http://test", user_id="u-eval-c")
    session._session_id = "sess-existing"
    captured = {}

    def fake_stream(method, url, json):
        captured["payload"] = json
        return _fake_stream()

    with patch.object(session._client, "stream", side_effect=fake_stream), \
         patch.object(session._client, "get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = []
        session.send({"role": "user", "content": "follow-up"})
    assert captured["payload"]["session_id"] == "sess-existing"


def test_send_returns_empty_tool_calls_when_endpoint_404s():
    from tests.evals.chat.chat_session import ChatSession

    session = ChatSession(base_url="http://test", user_id="u-eval-c")
    with patch.object(session._client, "stream", return_value=_fake_stream()), \
         patch.object(session._client, "get") as mock_get:
        mock_get.return_value.status_code = 404
        reply, tool_calls = session.send({"role": "user", "content": "x"})
    assert tool_calls == []
