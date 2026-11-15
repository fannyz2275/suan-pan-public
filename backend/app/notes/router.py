from __future__ import annotations
from app.provider_credentials.scope import gemini_client
"""Notes API: feedback POST, debug listing (Task 20), manual extraction trigger (Task 20)."""

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.db import get_admin_db
from app.db import get_admin_db as _db  # alias used by new dependency-injected endpoints
from app.notes.capture import emit_from_feedback
from app.notes.schema import NoteKind
from app.notes.store import _is_expired, _row_to_note, retire_note

router = APIRouter(prefix="/notes", tags=["notes"])


class NoteOut(BaseModel):
    id: UUID
    kind: NoteKind
    content: str
    tags: list[str]
    importance: int
    strength: int
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/user", response_model=list[NoteOut])
def list_user_notes(
    user=Depends(get_current_user),
    db=Depends(_db),
):
    """Return the current user's non-expired, non-superseded notes of kind fact or preference."""
    res = (
        db.table("user_notes")
        .select("id,user_id,kind,content,tags,importance,strength,source,provenance,entity_refs,created_at,expires_at,superseded_by")
        .eq("user_id", str(user.id))
        .in_("kind", [NoteKind.FACT.value, NoteKind.PREFERENCE.value])
        .is_("superseded_by", "null")
        .order("created_at", desc=True)
        .execute()
    )
    rows = [r for r in (res.data or []) if not _is_expired(r)]
    return [NoteOut(**_row_to_note(r).model_dump()) for r in rows]


@router.delete("/user/{note_id}", status_code=204)
def delete_user_note(
    note_id: UUID,
    user=Depends(get_current_user),
    db=Depends(_db),
):
    """Soft-delete a note by setting expires_at = now(). 404 if not found or not owned by user."""
    res = (
        db.table("user_notes")
        .select("id,user_id,expires_at")
        .eq("id", str(note_id))
        .eq("user_id", str(user.id))
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Note not found")
    retire_note(db, note_id)


class FeedbackLabels(BaseModel):
    helpful: bool = False
    not_helpful: bool = False
    too_technical: bool = False
    accurate_numbers: bool = False
    inaccurate_numbers: bool = False
    on_topic: bool = False
    off_topic: bool = False
    good_advice: bool = False
    bad_advice: bool = False


class FeedbackRequest(BaseModel):
    message_id: UUID
    labels: FeedbackLabels


@router.post("/feedback")
async def post_feedback(
    request: Request,
    body: FeedbackRequest,
    user=Depends(get_current_user),
):
    db = get_admin_db()

    asst = (
        db.table("chat_messages").select("id,role,session_id,content,created_at")
        .eq("id", str(body.message_id)).limit(1).execute().data
    )
    if not asst:
        raise HTTPException(404, "message not found")
    asst = asst[0]
    if asst["role"] != "assistant":
        raise HTTPException(400, "feedback only allowed on assistant messages")

    sess = (
        db.table("chat_sessions").select("user_id").eq("id", asst["session_id"])
        .limit(1).execute().data
    )
    if not sess or sess[0]["user_id"] != str(user.id):
        raise HTTPException(404, "message not found")

    prev = (
        db.table("chat_messages").select("content,created_at")
        .eq("session_id", asst["session_id"])
        .eq("role", "user")
        .lt("created_at", asst["created_at"])
        .order("created_at", desc=True).limit(1).execute().data
    )
    user_msg = prev[0]["content"] if prev else ""

    await emit_from_feedback(
        db=db,
        gemini=gemini_client(optional=True),
        user_id=user.id,
        message_id=str(body.message_id),
        session_id=asst["session_id"],
        user_message_text=user_msg,
        assistant_message_text=asst["content"] or "",
        labels=body.labels.model_dump(),
    )

    return {"ok": True}


import os
import time
from fastapi import Query
from app.notes.extraction import extract_for_user


@router.get("")
async def list_notes(
    request: Request,
    kind: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
):
    """Debug listing of the current user's live notes. v1 — gated by env flag."""
    if os.environ.get("NOTES_DEBUG_API") != "1":
        raise HTTPException(404, "not found")
    db = get_admin_db()
    q = (
        db.table("user_notes").select("*")
        .eq("user_id", str(user.id))
        .is_("superseded_by", "null")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if kind:
        q = q.eq("kind", kind)
    rows = q.execute().data or []
    return {"notes": rows}


_extract_now_last: dict[str, float] = {}


@router.post("/extract-now")
async def extract_now(request: Request, user=Depends(get_current_user)):
    now = time.time()
    last = _extract_now_last.get(str(user.id), 0)
    if now - last < 60:
        raise HTTPException(429, "rate limited")
    _extract_now_last[str(user.id)] = now

    db = get_admin_db()
    gemini = gemini_client(optional=True)
    n = await extract_for_user(db=db, gemini=gemini, user_id=user.id)
    return {"inserted": n}
