"""Score importance for user_notes rows still at the M0.2 default of 5.

Implements the project's backfill convention (see scripts/backfills/README.md):
exports NAME and a sync `apply(db, *, dry_run)`. Internally wraps the async
Gemini-scoring loop with asyncio.run.

Idempotency:
  - Belt: the runner records NAME in `applied_backfills` after a successful
    apply, so deploys never re-run a finished backfill.
  - Suspenders: each scored row gets `provenance.importance_source = 'llm'`,
    so a partial run resumes cleanly on the next invocation, AND failed rows
    that didn't get the sentinel are tracked in-process to avoid an infinite
    refetch loop within a single run.

Cost: ~$0.0001 per call. ~3000 notes ≈ $0.30 total.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional
from uuid import UUID

from app.notes.importance import score_importance
from app.notes.schema import NoteKind

logger = logging.getLogger(__name__)

NAME = "2026-05-02_note_importance"

BATCH = 25
SLEEP_BETWEEN_BATCHES = 1.0


def apply(db, *, dry_run: bool) -> None:
    """Entry point invoked by scripts.backfills._runner."""
    asyncio.run(_apply_async(db, dry_run=dry_run))


async def _apply_async(db, *, dry_run: bool) -> None:
    from app.provider_credentials.scope import credential_scope, gemini_client

    failed_ids: set[str] = set()
    total_scored = 0

    while True:
        pending = _fetch_pending(db, BATCH, exclude_ids=failed_ids)
        if not pending:
            logger.info("backfill complete: %d scored, %d failed",
                        total_scored, len(failed_ids))
            return

        if dry_run:
            logger.info("dry-run: would score %d rows", len(pending))
            for r in pending:
                logger.info("  %s [%s]", r["id"], r["kind"])
            return

        logger.info("backfill batch: %d rows", len(pending))
        for row in pending:
            try:
                async with credential_scope(row["user_id"]):
                    gemini = gemini_client()
                    new_imp = await _score_one(db, gemini, row)
                logger.info("  %s -> importance=%s", row["id"], new_imp)
                total_scored += 1
            except Exception:
                # Any failure: log + add to in-process exclude so the next
                # _fetch_pending call doesn't redeliver this row. Without
                # this guard, a transient row-specific failure could send
                # the loop into an infinite refetch.
                logger.exception("backfill failed for %s; will skip in this run",
                                 row["id"])
                failed_ids.add(str(row["id"]))
        await asyncio.sleep(SLEEP_BETWEEN_BATCHES)


def _fetch_pending(db, limit: int, *, exclude_ids: Optional[set[str]] = None) -> list[dict]:
    """Rows where importance is at the default (5) AND provenance does NOT
    record an LLM score. The combined condition is the resume sentinel.

    `exclude_ids` filters out rows that have already failed within the
    current run, preventing the refetch-forever loop when every in-batch
    row errors.
    """
    query = (
        db.table("user_notes")
        .select("id, user_id, kind, content, provenance")
        .eq("importance", 5)
    )
    if exclude_ids:
        # supabase-py renders this as a `not.in.(uuid1,uuid2,...)` filter.
        query = query.not_.in_("id", list(exclude_ids))
    rows = query.limit(limit).execute().data or []

    pending: list[dict] = []
    for r in rows:
        prov = r.get("provenance") or {}
        if prov.get("importance_source") != "llm":
            pending.append(r)
    return pending


async def _score_one(db, gemini, row: dict) -> Optional[int]:
    kind = row.get("kind")
    content = row.get("content") or ""
    try:
        kind_enum = NoteKind(kind) if kind else NoteKind.FACT
    except ValueError:
        kind_enum = NoteKind.FACT
    new_imp = await score_importance(gemini, content, kind_enum)
    prov = row.get("provenance") or {}
    prov["importance_source"] = "llm"
    db.table("user_notes").update(
        {"importance": new_imp, "provenance": prov}
    ).eq("id", row["id"]).execute()
    return new_imp
