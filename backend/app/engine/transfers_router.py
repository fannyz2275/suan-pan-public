"""HTTP surface for the transfer-handling feature.

Endpoints let the user review orphans, link/confirm/dismiss pairs, and trigger
a rescan. All routes are scoped to the current user; ownership is enforced by
always filtering updates and reads by `user_id`.
"""
import uuid
from datetime import date, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.db import get_admin_db as _db
from app.engine.transfers import PAIRING_WINDOW_DAYS, scan_transfers_for_user
from app.notes.capture import emit_fact_from_edit

router = APIRouter(prefix="/engine/transfers", tags=["transfers"])


def _get_txn_for_user(db, txn_id: str, user_id: str) -> dict:
    rows = (
        db.table("transactions")
        .select("*")
        .eq("id", txn_id)
        .eq("user_id", user_id)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return rows[0]


def _set_status(db, txn_id: str, user_id: str, payload: dict) -> None:
    db.table("transactions").update(payload).eq("id", txn_id).eq("user_id", user_id).execute()


async def _emit_txn_status_fact(
    *, db, request: Request, user_id, txn_id: str, before: dict, payload: dict
) -> None:
    """Best-effort: emit a fact note covering the transfer_status fields we just set."""
    after = {**before, **payload}
    await emit_fact_from_edit(
        db=db,
        # Transfer decisions are deterministic facts; do not wait for AI scoring.
        gemini=None,
        user_id=user_id,
        entity_kind="transaction",
        entity_id=txn_id,
        before=before,
        after=after,
    )


class LinkBody(BaseModel):
    other_txn_id: str


@router.post("/rescan")
async def rescan(user=Depends(get_current_user)):
    result = scan_transfers_for_user(_db(), user_id=str(user.id))
    return {"paired": result.paired_count, "orphans": result.orphan_count}


@router.get("/review")
async def review(
    window: Literal["90d", "all"] = Query("90d"),
    user=Depends(get_current_user),
):
    db = _db()
    q = (
        db.table("transactions")
        .select("*")
        .eq("user_id", str(user.id))
        .in_("transfer_status", ["auto_paired", "needs_review"])
    )
    if window == "90d":
        cutoff = (date.today() - timedelta(days=90)).isoformat()
        q = q.gte("date", cutoff)
    rows = q.order("date", desc=True).execute().data

    account_ids = list({r["account_id"] for r in rows if r.get("account_id")})
    accounts_by_id: dict[str, dict] = {}
    if account_ids:
        acct_rows = (
            db.table("accounts")
            .select("id,name")
            .in_("id", account_ids)
            .execute()
            .data
        )
        accounts_by_id = {a["id"]: a for a in acct_rows}

    out = []
    for r in rows:
        suggested: Optional[dict] = None
        if r["transfer_status"] == "needs_review":
            r_date = date.fromisoformat(r["date"])
            cutoff_lo = (r_date - timedelta(days=PAIRING_WINDOW_DAYS)).isoformat()
            cutoff_hi = (r_date + timedelta(days=PAIRING_WINDOW_DAYS)).isoformat()
            cand_rows = (
                db.table("transactions")
                .select("id,date,description,amount,account_id,transfer_status")
                .eq("user_id", str(user.id))
                .eq("amount", -float(r["amount"]))
                .gte("date", cutoff_lo)
                .execute()
                .data
            )
            cands = [
                c for c in cand_rows
                if c["account_id"] != r["account_id"]
                and c["date"] <= cutoff_hi
                and c.get("transfer_status") in (None, "needs_review")
            ]
            if len(cands) == 1:
                c = cands[0]
                suggested = {
                    "txn_id": c["id"],
                    "date": c["date"],
                    "amount": c["amount"],
                    "account_name": accounts_by_id.get(c["account_id"], {}).get("name", "—"),
                }

        out.append({
            "txn_id": r["id"],
            "date": r["date"],
            "description": r["description"],
            "amount": r["amount"],
            "account_name": accounts_by_id.get(r["account_id"], {}).get("name", "—"),
            "transfer_status": r["transfer_status"],
            "group_id": r.get("transfer_group_id"),
            "suggested_match": suggested,
        })
    return out


@router.post("/{txn_id}/mark-external")
async def mark_external(txn_id: str, request: Request, user=Depends(get_current_user)):
    db = _db()
    before = _get_txn_for_user(db, txn_id, str(user.id))
    payload = {"transfer_status": "external", "transfer_group_id": None}
    _set_status(db, txn_id, str(user.id), payload)
    await _emit_txn_status_fact(
        db=db, request=request, user_id=user.id, txn_id=txn_id, before=before, payload=payload,
    )
    # Best-effort policy derivation: future detection runs will skip txns
    # whose normalized description matches this. Failures logged + dropped.
    try:
        from app.policy import transfers as policy_transfers
        policy_transfers.derive_from_mark_external(
            db, user_id=user.id, description=before.get("description") or "",
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "policy.transfers.derive_from_mark_external failed for txn=%s", txn_id,
        )
    return {"ok": True}


@router.post("/{txn_id}/dismiss")
async def dismiss(txn_id: str, request: Request, user=Depends(get_current_user)):
    db = _db()
    txn = _get_txn_for_user(db, txn_id, str(user.id))
    gid = txn.get("transfer_group_id")
    was_auto_paired = txn.get("transfer_status") == "auto_paired"
    payload = {"transfer_status": "dismissed", "transfer_group_id": None}
    _set_status(db, txn_id, str(user.id), payload)
    await _emit_txn_status_fact(
        db=db, request=request, user_id=user.id, txn_id=txn_id, before=txn, payload=payload,
    )
    if gid and was_auto_paired:
        partners = (
            db.table("transactions").select("*")
            .eq("user_id", str(user.id))
            .eq("transfer_group_id", gid)
            .execute().data
        )
        for p in partners:
            if p["id"] != txn_id:
                partner_payload = {"transfer_status": None, "transfer_group_id": None}
                _set_status(db, p["id"], str(user.id), partner_payload)
                await _emit_txn_status_fact(
                    db=db, request=request, user_id=user.id, txn_id=p["id"],
                    before=p, payload=partner_payload,
                )
    return {"ok": True}


@router.post("/{txn_id}/confirm")
async def confirm(txn_id: str, request: Request, user=Depends(get_current_user)):
    """Promote an auto_paired pair to user_confirmed_internal."""
    db = _db()
    txn = _get_txn_for_user(db, txn_id, str(user.id))
    gid = txn.get("transfer_group_id")
    if not gid or txn.get("transfer_status") not in {"auto_paired", "user_confirmed_internal"}:
        raise HTTPException(status_code=400, detail="Transaction is not auto-paired")
    partners = (
        db.table("transactions").select("*")
        .eq("user_id", str(user.id))
        .eq("transfer_group_id", gid)
        .execute().data
    )
    payload = {"transfer_status": "user_confirmed_internal"}
    for p in partners:
        if p.get("transfer_status") not in {"auto_paired", "user_confirmed_internal"}:
            raise HTTPException(409, "Pair changed. Reload transfers before confirming.")
    for p in partners:
        if p.get("transfer_status") == "user_confirmed_internal":
            continue
        _set_status(db, p["id"], str(user.id), payload)
        await _emit_txn_status_fact(
            db=db, request=request, user_id=user.id, txn_id=p["id"],
            before=p, payload=payload,
        )
    return {"ok": True}


@router.post("/{txn_id}/link")
async def link(txn_id: str, body: LinkBody, request: Request, user=Depends(get_current_user)):
    if txn_id == body.other_txn_id:
        raise HTTPException(status_code=400, detail="Cannot link a transaction to itself")
    db = _db()
    uid = str(user.id)
    before_a = _get_txn_for_user(db, txn_id, uid)
    before_b = _get_txn_for_user(db, body.other_txn_id, uid)
    from app.config import settings
    identity_a, identity_b = {}, {}
    if settings.evidence_advisor_enabled:
        from decimal import Decimal
        aid, bid = before_a.get('account_id'), before_b.get('account_id')
        if not aid or not bid or aid == bid:
            raise HTTPException(400, 'Choose entries in different owned accounts')
        for account_id in (aid,bid):
            if not db.table('accounts').select('id').eq('id',account_id).eq('user_id',uid).execute().data:
                raise HTTPException(404, 'Account not found')
        a, b = Decimal(str(before_a['amount'])), Decimal(str(before_b['amount']))
        if not a.is_finite() or not b.is_finite() or a == 0 or a + b != 0:
            raise HTTPException(400, 'Transfer entries must have equal opposite amounts')
        if before_a.get('currency') and before_b.get('currency') and before_a['currency'] != before_b['currency']:
            raise HTTPException(400, 'Different currencies need manual reconciliation')
        identity_a = {'counterparty_account_id':bid,'counterparty_provenance':'user_confirmed'}
        identity_b = {'counterparty_account_id':aid,'counterparty_provenance':'user_confirmed'}
    gid = str(uuid.uuid4())
    payload = {"transfer_status": "user_confirmed_internal", "transfer_group_id": gid}
    _set_status(db, txn_id, uid, payload | identity_a)
    _set_status(db, body.other_txn_id, uid, payload | identity_b)
    await _emit_txn_status_fact(
        db=db, request=request, user_id=user.id, txn_id=txn_id, before=before_a, payload=payload,
    )
    await _emit_txn_status_fact(
        db=db, request=request, user_id=user.id, txn_id=body.other_txn_id,
        before=before_b, payload=payload,
    )
    return {"ok": True, "group_id": gid}
