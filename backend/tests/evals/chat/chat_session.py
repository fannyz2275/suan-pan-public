"""SSE client for the eval harness.

Sends one or more user messages to /advisor/chat, parses the SSE stream
for text and session_id, then fetches the structured tool-call log via
/eval/tool_calls/{session_id}.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from tests.evals.chat import EVAL_HEADERS


class ChatSession:
    def __init__(self, base_url: str, user_id: str, timeout: float = 60.0):
        headers = {**EVAL_HEADERS, "X-Eval-User-Id": user_id}
        self._client = httpx.Client(
            base_url=base_url, headers=headers, timeout=timeout,
        )
        self._session_id: str | None = None

    def send(self, msg: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
        """Send one message; return (reply_text, tool_calls)."""
        payload: dict[str, Any] = {"message": msg["content"]}
        if self._session_id:
            payload["session_id"] = self._session_id

        reply_text = ""
        with self._client.stream("POST", "/advisor/chat", json=payload) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if "text" in data:
                    reply_text += data["text"]
                elif "session_id" in data:
                    self._session_id = data["session_id"]

        tool_calls: list[dict[str, Any]] = []
        if self._session_id:
            r = self._client.get(f"/eval/tool_calls/{self._session_id}")
            if r.status_code == 200:
                tool_calls = r.json()
        return reply_text, tool_calls

    def close(self) -> None:
        self._client.close()
