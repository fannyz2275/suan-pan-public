"""Trust-UX HTTP surface for the policy layer.

Two read endpoints + one delete:

  GET    /policy/me           — active overrides grouped by domain plus the
                                top tool_priors per ctx_signature
  GET    /policy/tools/me     — tool priors only (lighter-weight; useful
                                when the FE only wants to render a tool
                                ordering hint)
  DELETE /policy/overrides/{id}  — soft-retires the override via
                                policy.store.retire (the engine immediately
                                stops applying it; the row is kept for audit)

All routes scope to the authenticated user; ownership is enforced both via
RLS on the underlying tables and via the explicit `.eq("user_id", ...)`
filter in the policy_store helpers.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.db import get_admin_db as _db
from app.policy import store as policy_store
from app.policy.schema import Domain

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/policy", tags=["policy"])

# Cap shown in /policy/me — beyond this the FE should paginate. Tuned for
# the common case (a user with at most a few dozen learned overrides per
# domain). Chosen empirically; bump if real-world usage shows truncation.
TOOL_PRIORS_TOP_K = 5


class LearnedOverride(BaseModel):
    id: UUID
    domain: Domain
    key: str
    value: dict
    strength: int
    last_reinforced_at: str
    created_at: str


class ToolPrior(BaseModel):
    tool_name: str
    ctx_signature: str
    success_count: int
    miss_count: int
    utility_score: float
    last_used_at: Optional[str] = None


class LearnedResponse(BaseModel):
    overrides: list[LearnedOverride]
    tool_priors: list[ToolPrior]


@router.get("/me", response_model=LearnedResponse)
async def get_learned(user=Depends(get_current_user)) -> LearnedResponse:
    db = _db()
    uid = str(user.id)

    # Tolerate the table being absent (migration not yet applied on this
    # DB). The FE renders an empty-state when both lists are empty, which
    # is a better UX than a dashboard-blocking 500. Anything else (Supabase
    # outage, network blip, programming bug) propagates so the user sees
    # a real failure and monitoring catches it.
    try:
        overrides = policy_store.list_for_user(db, user_id=uid)
    except Exception as exc:
        # Postgres reports missing tables with SQLSTATE 42P01 ("does not
        # exist"); PostgREST surfaces the same condition as PGRST205 with
        # the prose "Could not find the table". Match both — anything else
        # is a real failure and must propagate.
        msg = str(exc).lower()
        if (
            "42p01" in msg
            or "does not exist" in msg
            or "pgrst205" in msg
            or "could not find the table" in msg
        ):
            overrides = []
        else:
            logger.exception("policy.list_for_user failed for user=%s", uid)
            raise
    overrides_out = [
        LearnedOverride(
            id=o.id, domain=o.domain, key=o.key, value=o.value,
            strength=o.strength,
            last_reinforced_at=o.last_reinforced_at.isoformat()
                if hasattr(o.last_reinforced_at, "isoformat")
                else str(o.last_reinforced_at),
            created_at=o.created_at.isoformat()
                if hasattr(o.created_at, "isoformat")
                else str(o.created_at),
        )
        for o in overrides
    ]

    priors_rows = _load_tool_priors(db, uid)
    return LearnedResponse(overrides=overrides_out, tool_priors=priors_rows)


@router.get("/tools/me", response_model=list[ToolPrior])
async def get_tool_priors(user=Depends(get_current_user)) -> list[ToolPrior]:
    return _load_tool_priors(_db(), str(user.id))


def _load_tool_priors(db, user_id: str) -> list[ToolPrior]:
    """Top-K priors per ctx_signature, sorted by utility_score desc.

    The aggregation may not have run yet (PR #5 ships before the first
    nightly run necessarily completes), so an empty result is the common
    expected case — the FE handles it as 'no signal yet'."""
    try:
        rows = (
            db.table("user_tool_priors").select("*")
            .eq("user_id", user_id)
            .order("utility_score", desc=True)
            .execute()
            .data
        ) or []
    except Exception as exc:
        # Same pattern as /policy/me above: only swallow the missing-table
        # case (Postgres SQLSTATE 42P01 / PostgREST PGRST205), propagate
        # everything else so a real Supabase / network failure surfaces as
        # a 500 rather than a silent empty list.
        msg = str(exc).lower()
        if (
            "42p01" in msg
            or "does not exist" in msg
            or "pgrst205" in msg
            or "could not find the table" in msg
        ):
            return []
        logger.exception("policy.get_tool_priors load failed for user=%s", user_id)
        raise

    # Group by ctx, take top-K each.
    by_ctx: dict[str, list[dict]] = {}
    for r in rows:
        by_ctx.setdefault(r.get("ctx_signature") or "other", []).append(r)
    out: list[ToolPrior] = []
    for ctx, group in by_ctx.items():
        for r in group[:TOOL_PRIORS_TOP_K]:
            out.append(ToolPrior(
                tool_name=r["tool_name"],
                ctx_signature=r.get("ctx_signature") or "other",
                success_count=int(r.get("success_count") or 0),
                miss_count=int(r.get("miss_count") or 0),
                utility_score=float(r.get("utility_score") or 0.0),
                last_used_at=str(r["last_used_at"]) if r.get("last_used_at") else None,
            ))
    return out


@router.delete("/overrides/{override_id}", status_code=204)
async def retire_override(override_id: UUID, user=Depends(get_current_user)):
    """Soft-delete an override the user wants Suan-Pan to forget. Verifies
    ownership before retiring — a stranger can't retire your overrides
    even with knowledge of the id."""
    db = _db()
    rows = (
        db.table("user_engine_overrides").select("user_id")
        .eq("id", str(override_id)).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="override not found")
    if rows[0]["user_id"] != str(user.id):
        # Same shape as 404 to avoid leaking the existence of other users' rows.
        raise HTTPException(status_code=404, detail="override not found")
    policy_store.retire(db, override_id)
    return None
