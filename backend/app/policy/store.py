"""DB helpers for user_engine_overrides.

Engine reads (`lookup`) are best-effort and wrapped in try/except by callers
— a missing or corrupt policy must never break the engine call. Writes
happen service-side; RLS-protected select-own is the only auth-side surface.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from app.policy.schema import Domain, Override

logger = logging.getLogger(__name__)


def lookup(
    db, *, user_id: UUID | str, domain: Domain | str, key: str,
) -> Optional[Override]:
    """Return the active override for (user, domain, key) or None.

    Engine call sites wrap this in try/except → default. Failures here
    must not propagate (a bad policy table read should fall back to
    unbiased engine behavior, not 500 the user's request).
    """
    try:
        rows = (
            db.table("user_engine_overrides").select("*")
            .eq("user_id", str(user_id))
            .eq("domain", domain.value if isinstance(domain, Domain) else domain)
            .eq("key", key)
            .is_("retired_at", "null")
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        logger.exception("policy.lookup failed for (%s, %s, %s)", user_id, domain, key)
        return None
    if not rows:
        return None
    return _row_to_override(rows[0])


def insert_or_reinforce(
    db, *, user_id: UUID | str, domain: Domain | str, key: str,
    value: dict[str, Any], source_note_id: Optional[UUID] = None,
) -> Override:
    """Upsert by (user_id, domain, key). On conflict bump strength + reset
    last_reinforced_at. Used by every domain-specific derive_* function.

    Postgrest doesn't expose ON CONFLICT directly via the table API, so we
    do an explicit lookup-then-update / insert dance. Race-safe under the
    DB unique constraint: if a parallel insert won, the second insert
    raises and we fall through to reinforce.
    """
    domain_str = domain.value if isinstance(domain, Domain) else domain
    existing = (
        db.table("user_engine_overrides").select("id, strength")
        .eq("user_id", str(user_id))
        .eq("domain", domain_str)
        .eq("key", key)
        .limit(1)
        .execute()
        .data
    )
    if existing:
        new_strength = (existing[0].get("strength") or 1) + 1
        res = (
            db.table("user_engine_overrides").update({
                "value": value,
                "strength": new_strength,
                "last_reinforced_at": datetime.now(timezone.utc).isoformat(),
                "retired_at": None,  # un-retire if previously soft-deleted
            }).eq("id", existing[0]["id"]).execute()
        )
        return _row_to_override(res.data[0])

    payload = {
        "user_id": str(user_id),
        "domain": domain_str,
        "key": key,
        "value": value,
        "source_note_id": str(source_note_id) if source_note_id else None,
        "strength": 1,
    }
    res = db.table("user_engine_overrides").insert(payload).execute()
    return _row_to_override(res.data[0])


def retire(db, override_id: UUID | str) -> None:
    """Soft-delete: set retired_at = now(). Engine reads filter this out.
    Row is kept for audit + undo (the trust UX in PR #5)."""
    db.table("user_engine_overrides").update({
        "retired_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", str(override_id)).execute()


def list_for_user(
    db, *, user_id: UUID | str, domain: Domain | str | None = None,
    include_retired: bool = False,
) -> list[Override]:
    """Used by the trust-UX 'What Suan-Pan has learned' settings page (PR #5).
    Optionally filter by domain or include retired rows for audit views."""
    q = (
        db.table("user_engine_overrides").select("*")
        .eq("user_id", str(user_id))
    )
    if domain is not None:
        q = q.eq("domain", domain.value if isinstance(domain, Domain) else domain)
    if not include_retired:
        q = q.is_("retired_at", "null")
    rows = q.order("last_reinforced_at", desc=True).execute().data or []
    return [_row_to_override(r) for r in rows]


def _row_to_override(row: dict) -> Override:
    return Override(
        id=row["id"],
        user_id=row["user_id"],
        domain=row["domain"],
        key=row["key"],
        value=row.get("value") or {},
        source_note_id=row.get("source_note_id"),
        strength=row.get("strength") or 1,
        created_at=row["created_at"],
        last_reinforced_at=row["last_reinforced_at"],
        retired_at=row.get("retired_at"),
    )
