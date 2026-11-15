"""Aggregate tool_call_logs into user_tool_priors with Wilson lower-bound
utility scores.

Designed for the project's discovery-based runner (see
scripts/backfills/_runner.py). Idempotent: each run reads the full log
table, recomputes per-(user, tool, ctx_signature) success/miss counts +
Wilson lower bounds, and upserts user_tool_priors.

Schedule via the runner; once user_tool_priors is materialized, the chat
handler reads it on every turn to reorder tools per user. A future PR
will wire this to a cron + add a retention sweep that trims aggregated
log rows older than 180 days.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from app.policy.tool_priors import wilson_lower_bound

logger = logging.getLogger(__name__)

NAME = "2026-05-03_aggregate_tool_priors"

# Pull logs in chunks so a power user with 100k+ rows doesn't OOM the
# aggregator. Each chunk is folded into the in-memory totals; the upsert
# happens once at the end.
CHUNK = 1000


def apply(db, *, dry_run: bool) -> None:
    """Entry point invoked by scripts.backfills._runner."""
    counts: dict[tuple[str, str, str], dict[str, object]] = defaultdict(
        lambda: {"success": 0, "miss": 0, "last_used_at": None}
    )

    offset = 0
    while True:
        rows = (
            db.table("tool_call_logs")
            .select("user_id, tool_name, ctx_signature, succeeded, created_at")
            .range(offset, offset + CHUNK - 1)
            .execute()
            .data
            or []
        )
        if not rows:
            break

        for r in rows:
            ctx = r.get("ctx_signature") or "other"
            key = (r["user_id"], r["tool_name"], ctx)
            bucket = counts[key]
            if r.get("succeeded"):
                bucket["success"] = int(bucket["success"]) + 1
            else:
                bucket["miss"] = int(bucket["miss"]) + 1
            created = r.get("created_at")
            current = bucket["last_used_at"]
            if isinstance(created, str) and (current is None or created > current):
                bucket["last_used_at"] = created

        offset += CHUNK

    logger.info(
        "aggregating %d (user, tool, ctx) buckets from tool_call_logs",
        len(counts),
    )
    if dry_run:
        for (user_id, tool_name, ctx), bucket in list(counts.items())[:20]:
            total = int(bucket["success"]) + int(bucket["miss"])
            score = wilson_lower_bound(int(bucket["success"]), total)
            logger.info(
                "  user=%s tool=%s ctx=%s success=%d miss=%d wilson=%.3f",
                user_id, tool_name, ctx, bucket["success"], bucket["miss"], score,
            )
        return

    for (user_id, tool_name, ctx), bucket in counts.items():
        success = int(bucket["success"])
        miss = int(bucket["miss"])
        total = success + miss
        utility = wilson_lower_bound(success, total)
        payload = {
            "user_id": user_id,
            "tool_name": tool_name,
            "ctx_signature": ctx,
            "success_count": success,
            "miss_count": miss,
            "utility_score": utility,
            "last_used_at": bucket["last_used_at"],
        }
        # supabase-py's .upsert needs the unique-key columns specified so it
        # uses ON CONFLICT, not INSERT-then-fail.
        db.table("user_tool_priors").upsert(
            payload, on_conflict="user_id,tool_name,ctx_signature",
        ).execute()
