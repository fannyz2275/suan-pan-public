"""In-process tool-call recorder used by Spec C eval harness.

Behavior is gated on EVAL_MOCKS=1. In production the env var is unset and
record_tool_call is a no-op; the storage dict stays empty.

Storage is process-local and unbounded by design — eval runs are short-lived
and clear_session is called by the harness between scenarios.
"""
from __future__ import annotations

import os
from typing import Any

EVAL_MOCKS_ENABLED = os.getenv("EVAL_MOCKS") == "1"

_eval_tool_calls: dict[str, list[dict[str, Any]]] = {}


def record_tool_call(
    session_id: str,
    name: str,
    args: dict[str, Any],
    result_data: Any,
) -> None:
    """Append one tool call to this session's log. No-op when EVAL_MOCKS unset."""
    if not EVAL_MOCKS_ENABLED:
        return
    _eval_tool_calls.setdefault(session_id, []).append({
        "name": name,
        "args": args,
        "result_data": result_data,
    })


def get_tool_calls(session_id: str) -> list[dict[str, Any]]:
    """Return the recorded tool calls for a session, or [] if none recorded."""
    return list(_eval_tool_calls.get(session_id, []))


def clear_session(session_id: str) -> None:
    """Drop a session's log; called by harness between scenarios."""
    _eval_tool_calls.pop(session_id, None)
