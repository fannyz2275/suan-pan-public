"""Per-user tool-ordering signal layer.

Two surfaces:
  log_tool_call   — one INSERT into tool_call_logs per tool invocation.
                    Hot path; never raises.
  reorder_tools   — at chat start, reorder the tool list shown to Gemini
                    so this user's historically-most-useful tools for the
                    current ctx_signature surface first. Falls back to the
                    input order on any failure.

Aggregation (logs → user_tool_priors) lives in a separate backfill module
(scripts/backfills/aggregate_tool_priors.py) and runs nightly.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from typing import Any, Iterable, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def args_hash(args: dict) -> str:
    """Deterministic sha256 hex of `args` so identical retries dedupe in
    aggregation. Keys are sorted to make the hash insensitive to dict
    iteration order. Truncated to 16 chars — enough collision space for
    per-user logs."""
    if not args:
        return ""
    payload = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def log_tool_call(
    db, *,
    user_id: UUID | str,
    session_id: Optional[str],
    message_id: Optional[str],
    tool_name: str,
    args: Optional[dict],
    ctx_signature: Optional[str],
    succeeded: bool,
    duration_ms: Optional[int] = None,
) -> None:
    """Insert a single tool-call log row. Best-effort: any failure is
    logged + dropped so the chat turn proceeds normally."""
    try:
        db.table("tool_call_logs").insert({
            "user_id": str(user_id),
            "session_id": session_id,
            "message_id": message_id,
            "tool_name": tool_name,
            "args_hash": args_hash(args or {}),
            "ctx_signature": ctx_signature,
            "succeeded": bool(succeeded),
            "duration_ms": duration_ms,
        }).execute()
    except Exception:
        logger.exception(
            "tool_priors.log_tool_call failed for user=%s tool=%s",
            user_id, tool_name,
        )


def _load_priors_for_ctx(
    db, *, user_id: UUID | str, ctx_signature: str,
) -> dict[str, float]:
    """Return {tool_name: utility_score} for this user + ctx_signature.
    Empty dict on lookup failure — caller falls back to default ordering."""
    try:
        rows = (
            db.table("user_tool_priors").select("tool_name, utility_score")
            .eq("user_id", str(user_id))
            .eq("ctx_signature", ctx_signature)
            .execute()
            .data
        ) or []
    except Exception:
        logger.exception(
            "tool_priors._load_priors_for_ctx failed for user=%s ctx=%s",
            user_id, ctx_signature,
        )
        return {}
    return {r["tool_name"]: float(r.get("utility_score") or 0.0) for r in rows}


def reorder_tools(
    db, *,
    user_id: UUID | str,
    ctx_signature: str,
    tools: list[Any],
    name_attr: str = "name",
) -> list[Any]:
    """Reorder `tools` so the highest-utility tools for this user + ctx
    come first. Tools without a recorded prior preserve their relative
    order at the back. Best-effort: returns the input unchanged on any
    failure."""
    if not tools:
        return tools
    priors = _load_priors_for_ctx(
        db, user_id=user_id, ctx_signature=ctx_signature,
    )
    if not priors:
        return tools

    # Stable sort: tools with priors descend by utility_score; tools without
    # priors keep their original input order at the tail.
    indexed = list(enumerate(tools))
    indexed.sort(key=lambda pair: (
        # Tools with priors first (False < True).
        getattr(pair[1], name_attr, None) not in priors,
        # Among priored tools, descending utility_score.
        -priors.get(getattr(pair[1], name_attr, None), 0.0),
        # Stable tail: preserve original index for unpriored tools.
        pair[0],
    ))
    return [t for _, t in indexed]


def wilson_lower_bound(success: int, total: int, z: float = 1.96) -> float:
    """Wilson score interval lower bound. Penalizes low-volume estimates so
    a 1-for-1 tool doesn't outrank a 50-for-60 tool. Used by the nightly
    aggregation job in scripts/backfills/aggregate_tool_priors.py.

    z=1.96 is the standard 95%-confidence lower bound."""
    if total <= 0:
        return 0.0
    p = success / total
    z2 = z * z
    denom = 1 + z2 / total
    centre = p + z2 / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total))
    return max(0.0, (centre - margin) / denom)
