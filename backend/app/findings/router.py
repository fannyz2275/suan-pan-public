from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.db import get_admin_db
from app.findings.schema import Decision, Finding
from app.findings.service import list_pending_findings

router = APIRouter(prefix="/findings", tags=["findings"])


class FindingsResponse(BaseModel):
    findings: list[Finding]
    total: int


class CountResponse(BaseModel):
    count: int


def _load_pending(user_id: str) -> list[Finding]:
    db = get_admin_db()
    rules = (
        db.table("recurring_rules")
        .select("*")
        .eq("user_id", user_id)
        .in_("status", ["proposed", "pending_review"])
        .execute()
        .data
        or []
    )
    txns = (
        db.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .eq("transfer_status", "needs_review")
        .execute()
        .data
        or []
    )
    return list_pending_findings(rules, txns)


@router.get("", response_model=FindingsResponse)
def get_findings(user=Depends(get_current_user)):
    findings = _load_pending(str(user.id))
    return FindingsResponse(findings=findings, total=len(findings))


@router.get("/count", response_model=CountResponse)
def get_findings_count(user=Depends(get_current_user)):
    return CountResponse(count=len(_load_pending(str(user.id))))


_TERMINAL_RULE_STATUSES = {"user_confirmed", "user_rejected", "auto_applied"}
_TERMINAL_TRANSFER_STATUSES = {
    "user_confirmed_internal",
    "external",
    "dismissed",
    "auto_paired",
}


@router.post("/{kind}/{finding_id}/decision")
def post_decision(
    kind: str,
    finding_id: str,
    body: Decision,
    user=Depends(get_current_user),
):
    db = get_admin_db()
    if kind == "recurring":
        rows = (
            db.table("recurring_rules")
            .select("status")
            .eq("id", finding_id)
            .eq("user_id", str(user.id))
            .execute()
            .data
            or []
        )
        if not rows:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "rule not found")
        current = rows[0]["status"]
        if current in _TERMINAL_RULE_STATUSES:
            return {"status": "noop", "previous": current}
        new_status = "user_confirmed" if body.decision == "accept" else "user_rejected"
        db.table("recurring_rules").update({"status": new_status}).eq("id", finding_id).execute()
        return {"status": new_status}

    if kind == "transfer":
        rows = (
            db.table("transactions")
            .select("transfer_status")
            .eq("id", finding_id)
            .eq("user_id", str(user.id))
            .execute()
            .data
            or []
        )
        if not rows:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "transaction not found")
        current = rows[0]["transfer_status"]
        if current in _TERMINAL_TRANSFER_STATUSES:
            return {"status": "noop", "previous": current}
        new_status = (
            "user_confirmed_internal" if body.decision == "accept" else "external"
        )
        db.table("transactions").update({"transfer_status": new_status}).eq(
            "id", finding_id
        ).execute()
        return {"status": new_status}

    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown kind: {kind}")
