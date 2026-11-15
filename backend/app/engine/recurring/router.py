from __future__ import annotations
from app.provider_credentials.scope import gemini_client

import asyncio
from datetime import date, timedelta
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.db import get_admin_db as _db
from app.engine.recurring.detector import WINDOW_DAYS, detect_recurring_rules
from app.engine.recurring.rule_match import apply_rule_matches
from app.engine.recurring.schema import RecurringRule, Status
from app.engine.recurring.store import load_rules, upsert_rules
from app.notes.capture import emit_fact_from_edit

router = APIRouter(prefix="/engine/recurring", tags=["recurring"])


class DetectResponse(BaseModel):
    rules: List[RecurringRule]


class RulesResponse(BaseModel):
    rules: List[RecurringRule]


class PatchRequest(BaseModel):
    action: Literal["confirm", "reject", "edit"]
    keyword: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    frequency: Optional[str] = None


def run_detection(user_id: UUID, client) -> List[RecurringRule]:
    active = load_rules(client, user_id)
    today = date.today()
    txns = []
    offset = 0
    while True:
        page = (client.table("transactions").select("*").eq("user_id", str(user_id))
                .gte("date", (today - timedelta(days=WINDOW_DAYS)).isoformat())
                .lte("date", today.isoformat()).order("date").order("id")
                .range(offset, offset + 999).execute().data or [])
        txns.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    results = detect_recurring_rules(
        transactions=txns or [],
        active_rules=active,
        user_id=user_id,
        today=today,
        # Interactive scans must not wait on sequential AI tie-breakers.
        allow_llm=False,
    )

    # Apply per-user recurring policy: drop newly-PROPOSED rules whose
    # keyword matches a rejected-policy entry, so the user doesn't have
    # to re-reject the same cluster on every detection pass. Existing
    # user-confirmed rules are NEVER filtered — they're authoritative.
    from app.engine.recurring.schema import Status
    from app.policy import recurring as policy_recurring
    new_proposals = [r for r in results if r.status == Status.PROPOSED]
    if new_proposals:
        keep_keywords = policy_recurring.filter_rejected_keywords(
            client, user_id=user_id, keywords={r.keyword for r in new_proposals},
        )
        results = [
            r for r in results
            if r.status != Status.PROPOSED or r.keyword in keep_keywords
        ]

    upsert_rules(client, results)
    return results


@router.post("/detect", response_model=DetectResponse)
async def detect(user=Depends(get_current_user)):
    client = _db()
    rules = await asyncio.to_thread(run_detection, UUID(str(user.id)), client)
    return DetectResponse(rules=rules)


@router.get("/rules", response_model=RulesResponse)
async def list_rules(user=Depends(get_current_user)):
    client = _db()
    rules = load_rules(client, UUID(str(user.id)))
    return RulesResponse(rules=rules)


def _update_rule_status(client, rule_id: UUID, user_id: UUID, patch: PatchRequest) -> RecurringRule:
    rows = (
        client.table("recurring_rules")
        .select("*")
        .eq("id", str(rule_id))
        .eq("user_id", str(user_id))
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="rule not found")
    rule = RecurringRule(**rows[0])
    if patch.action == "confirm":
        rule = rule.model_copy(update={"status": Status.USER_CONFIRMED, "confidence": 1.0})
    elif patch.action == "reject":
        rule = rule.model_copy(update={"status": Status.USER_REJECTED})
    elif patch.action == "edit":
        update_fields = {k: v for k, v in patch.model_dump().items() if v is not None and k != "action"}
        rule = rule.model_copy(update={**update_fields, "status": Status.USER_CONFIRMED, "confidence": 1.0})
    upsert_rules(client, [rule])
    return rule


@router.patch("/rules/{rule_id}", response_model=Optional[RecurringRule])
async def patch_rule(
    rule_id: UUID,
    body: PatchRequest,
    request: Request,
    user=Depends(get_current_user),
):
    client = _db()
    # Snapshot the row before the update so we can emit a precise diff.
    before_rows = (
        client.table("recurring_rules")
        .select("*")
        .eq("id", str(rule_id))
        .eq("user_id", str(user.id))
        .execute()
        .data
    ) if client is not None else []
    before = before_rows[0] if before_rows else {}

    rule = _update_rule_status(client, rule_id, UUID(str(user.id)), body)

    if rule is not None and before:
        try:
            after = rule.model_dump(mode="json")
        except Exception:
            after = {}
        await emit_fact_from_edit(
            db=client,
            gemini=gemini_client(optional=True),
            user_id=user.id,
            entity_kind="recurring",
            entity_id=str(rule_id),
            before=before,
            after=after,
        )

        # Best-effort policy derivation. When the user rejects a rule, write
        # a `reject:<keyword>` policy so the next detection run skips the
        # same cluster instead of re-proposing it. Failures logged + dropped.
        new_status = (after.get("status") if isinstance(after, dict) else None)
        if new_status == "user_rejected":
            try:
                from app.policy import recurring as policy_recurring
                policy_recurring.derive_from_rejection(
                    client, user_id=user.id, keyword=before.get("keyword") or "",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "policy.recurring.derive_from_rejection failed for rule=%s",
                    rule_id,
                )
    return rule


class MatchBinding(BaseModel):
    transaction_id: str
    rule_id: str
    rule_keyword: str
    rule_frequency: str


class MatchResponse(BaseModel):
    bindings: List[MatchBinding]


@router.get("/match", response_model=MatchResponse)
async def match_transactions(
    date_from: date,
    date_to: date,
    user=Depends(get_current_user),
):
    """Return {transaction_id → rule} bindings for active rules in a date range.

    Used by the Cash Flow category-breakdown table to decorate recurring rows
    without re-implementing the matcher on the frontend.
    """
    client = _db()
    uid = UUID(str(user.id))
    rules = load_rules(client, uid)
    active = [r for r in rules if r.status in (Status.USER_CONFIRMED, Status.AUTO_APPLIED)]
    if not active:
        return MatchResponse(bindings=[])

    txns = (
        client.table("transactions")
        .select("id,description,amount")
        .eq("user_id", str(uid))
        .gte("date", date_from.isoformat())
        .lte("date", date_to.isoformat())
        .execute()
        .data
        or []
    )

    match_result = apply_rule_matches(txns, active)
    rule_by_id = {r.id: r for r in active}
    bindings = []
    for txn_id, rule_id in match_result.bindings.items():
        rule = rule_by_id.get(rule_id)
        if rule is None:
            continue
        bindings.append(
            MatchBinding(
                transaction_id=str(txn_id),
                rule_id=str(rule_id),
                rule_keyword=rule.keyword,
                rule_frequency=str(rule.frequency),
            )
        )
    return MatchResponse(bindings=bindings)
