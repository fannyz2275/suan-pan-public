from app.provider_credentials.scope import gemini_client
from fastapi import APIRouter, Depends, Request, Response

from app.auth.middleware import get_current_user
from app.db import get_admin_db as _db
from app.notes.capture import emit_fact_from_edit
from app.profile.scales import all_scales
from app.profile.schemas import ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])

# Columns the Overview tab is allowed to read. annual_income / monthly_expenses
# are intentionally absent — those columns were dropped in PR-A's migration;
# T2 derives both from real transactions. The advisor-memory fields
# (preferences, financial_status, financial_goals) live on the same row but
# are deliberately filtered out — they're for cross-session continuity, not
# something the user edits or browses.
#
# TODO(post-rollout): drop the legacy `risk_tolerance` / `time_horizon` enum
# columns once the v2 cols are confirmed populated for all users; remove them
# from this string and from ProfileUpdate at the same time.
_OVERVIEW_FIELDS = (
    "id,age,risk_tolerance,risk_tolerance_v2,time_horizon,time_horizon_v2,"
    "employment_status,region,dependents,use_category_baselines,"
    "created_at,updated_at"
)


def _ensure_profile(db, uid: str) -> dict:
    """Return the user's profile row, creating a default if missing."""
    rows = db.table("profiles").select(_OVERVIEW_FIELDS).eq("id", uid).execute().data
    if rows:
        return rows[0]
    db.table("profiles").upsert({"id": uid, "risk_tolerance": "moderate"}).execute()
    return db.table("profiles").select(_OVERVIEW_FIELDS).eq("id", uid).execute().data[0]


@router.get("")
async def get_profile(user=Depends(get_current_user)):
    return _ensure_profile(_db(), str(user.id))


@router.get("/scales")
async def get_scales():
    """1-5 anchor sentences for the risk_tolerance / time_horizon sliders.

    Read by the ProfileCard sliders so backend prompt copy and UI tooltip
    copy never drift apart. No auth required — the data is static, public
    UX copy with no per-user secrets.
    """
    return all_scales()


@router.patch("")
async def patch_profile(
    body: ProfileUpdate,
    request: Request,
    user=Depends(get_current_user),
):
    uid = str(user.id)
    db = _db()
    before = _ensure_profile(db, uid)  # guarantee row exists
    patch = body.model_dump(exclude_none=True)
    if patch:
        db.table("profiles").update(patch).eq("id", uid).execute()
    after = db.table("profiles").select(_OVERVIEW_FIELDS).eq("id", uid).execute().data[0]

    if patch:
        await emit_fact_from_edit(
            db=db,
            gemini=gemini_client(optional=True),
            user_id=user.id,
            entity_kind="profile",
            entity_id=uid,
            before=before,
            after=after,
        )

    return after


@router.get("/memory")
async def get_memory(user=Depends(get_current_user)):
    """Return the advisor-memory fields. The legacy JSONB columns
    (preferences/financial_status/financial_goals) were dropped in the
    Phase-0 PR-#4 migration; durable memory now lives in user_notes and the
    snapshot. Kept as an always-empty 200 to satisfy older FE callers
    (Dashboard, ProfileCard) without surfacing a 500 on dashboard load."""
    return {
        "preferences": None,
        "financial_status": None,
        "financial_goals": None,
    }


@router.delete("/memory")
async def delete_memory(user=Depends(get_current_user)):
    """Clear the advisor's durable memory of the user. Idempotent. The
    legacy JSONB blobs no longer exist on this row; the route is retained
    so the FE 'Clear memory' button keeps returning 204."""
    return Response(status_code=204)
