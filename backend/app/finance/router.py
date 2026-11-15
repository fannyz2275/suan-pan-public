from app.provider_credentials.scope import gemini_client
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth.middleware import get_current_user
from app.db import get_admin_db as _db
from app.engine.snapshot import notional_value
from app.finance.balance_history import cache_patch, record_history
from app.finance.schemas import (
    AccountCreate, AccountOut,
    GoalCreate, GoalOut, GoalUpdate,
    TransactionOut,
)
from app.notes.capture import emit_fact_from_edit

router = APIRouter(prefix="/finance", tags=["finance"])


def _attach_notional(account: dict) -> dict:
    return {**account, "notional_value": notional_value(account)}


# --- Accounts ---

@router.get("/accounts", response_model=List[AccountOut])
async def list_accounts(user=Depends(get_current_user)):
    rows = _db().table("accounts").select("*").eq("user_id", str(user.id)).eq("is_active", True).execute().data
    return [_attach_notional(a) for a in rows]


@router.post("/accounts", response_model=AccountOut)
async def create_account(body: AccountCreate, user=Depends(get_current_user)):
    db = _db()
    uid = str(user.id)
    data = body.model_dump()
    data["user_id"] = uid
    data.update(cache_patch(None, body.balance))
    row = db.table("accounts").insert(data).execute().data[0]
    # History records the notional value, not the raw balance — for property /
    # RSU / business this captures re-valuations honestly. notional_value falls
    # through to balance for liquid/investment/debt types.
    record_history(
        db, account_id=row["id"], user_id=uid,
        balance=notional_value(row), source="manual",
    )
    return _attach_notional(row)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: str,
    body: AccountCreate,
    request: Request,
    user=Depends(get_current_user),
):
    db = _db()
    uid = str(user.id)
    existing = (
        db.table("accounts")
        .select("*")
        .eq("id", account_id).eq("user_id", uid).limit(1).execute().data
    )
    if not existing:
        raise HTTPException(404, "Account not found")
    before = existing[0]

    payload = body.model_dump()
    payload.update(cache_patch(before, body.balance))
    result = db.table("accounts").update(payload).eq("id", account_id).eq("user_id", uid).execute()
    after = result.data[0]
    # Record any change to the notional value — covers raw-balance edits AND
    # re-valuations of property/RSU/business via estimated_value/ownership_pct.
    notional_before = notional_value(before)
    notional_after = notional_value(after)
    if notional_after != notional_before:
        record_history(
            db, account_id=account_id, user_id=uid,
            balance=notional_after, source="manual",
        )

    # Best-effort fact-note emission. Never fails the request.
    await emit_fact_from_edit(
        db=db,
        gemini=gemini_client(optional=True),
        user_id=user.id,
        entity_kind="account",
        entity_id=account_id,
        before=before,
        after=after,
    )

    return _attach_notional(after)


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, user=Depends(get_current_user)):
    _db().table("accounts").update({"is_active": False}).eq("id", account_id).eq("user_id", str(user.id)).execute()
    return {"ok": True}


# --- Goals ---

@router.get("/goals", response_model=List[GoalOut])
async def list_goals(user=Depends(get_current_user)):
    return _db().table("goals").select("*").eq("user_id", str(user.id)).eq("is_active", True).execute().data


@router.post("/goals", response_model=GoalOut)
async def create_goal(body: GoalCreate, user=Depends(get_current_user)):
    data = body.model_dump()
    data["user_id"] = str(user.id)
    return _db().table("goals").insert(data).execute().data[0]


@router.patch("/goals/{goal_id}", response_model=GoalOut)
async def update_goal(
    goal_id: str,
    body: GoalUpdate,
    request: Request,
    user=Depends(get_current_user),
):
    db = _db()
    uid = str(user.id)
    existing = db.table("goals").select("*").eq("id", goal_id).eq("user_id", uid).execute().data
    if not existing:
        raise HTTPException(404, "Goal not found")
    before = existing[0]

    patch = body.model_dump(exclude_none=True)
    if not patch:
        # No-op patch — return current row unchanged.
        return before
    result = db.table("goals").update(patch).eq("id", goal_id).eq("user_id", uid).execute()
    if not result.data:
        raise HTTPException(404, "Goal not found")
    after = result.data[0]

    await emit_fact_from_edit(
        db=db,
        gemini=gemini_client(optional=True),
        user_id=user.id,
        entity_kind="goal",
        entity_id=goal_id,
        before=before,
        after=after,
    )

    return after


# --- Transactions ---

@router.get("/transactions", response_model=List[TransactionOut])
async def list_transactions(
    limit: int = 100,
    offset: int = 0,
    account_id: str | None = None,
    category: str | None = None,
    exclude_transfers: bool = True,
    user=Depends(get_current_user),
):
    q = _db().table("transactions").select("*").eq("user_id", str(user.id))
    if account_id:
        q = q.eq("account_id", account_id)
    if category:
        q = q.eq("category", category)
    if exclude_transfers:
        # Exclude rows recognized as transfers (auto-paired, user-confirmed,
        # or marked external) so the spending view isn't polluted. Keep NULL
        # rows and `dismissed` ("not a transfer") — the latter is explicitly
        # real spending. SQL `NOT IN (...)` drops NULLs because
        # `NULL NOT IN (...)` evaluates to NULL, not TRUE, hence the OR form.
        q = q.or_(
            "transfer_status.is.null,"
            "and("
            "transfer_status.neq.auto_paired,"
            "transfer_status.neq.user_confirmed_internal,"
            "transfer_status.neq.external"
            ")"
        )
    return q.order("date", desc=True).order("id").range(offset, offset + limit - 1).execute().data
