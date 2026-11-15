"""Capture entry points: entity-edit diffs + message feedback."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.notes.importance import score_importance
from app.notes.schema import NewNote, NoteKind, NoteSource
from app.notes.store import insert_note, supersede_notes

logger = logging.getLogger(__name__)

# Fields that are numeric/enum/structured — use deterministic templates, no LLM.
_TEMPLATE_FIELDS = {
    "balance", "amount", "target_amount", "current_progress",
    "amount_median", "frequency", "status", "type",
    "transfer_status", "is_primary", "use_category_baselines",
    "monthly_expenses", "annual_income",
}

_ENTITY_LABELS = {
    "account": "account", "goal": "goal",
    "recurring": "recurring rule", "transaction": "transaction",
    "profile": "profile", "category_baseline": "category baseline",
}


def _diff_fields(before: dict, after: dict) -> list[tuple[str, Any, Any]]:
    """Return [(field, old, new)] for fields where after[k] != before.get(k)."""
    out = []
    for k, v_new in after.items():
        v_old = before.get(k)
        if v_old != v_new:
            out.append((k, v_old, v_new))
    return out


def _format_diff_template(entity_kind: str, entity_id: str, field: str, old: Any, new: Any) -> str:
    label = _ENTITY_LABELS.get(entity_kind, entity_kind)
    return f"User updated {label} {entity_id} {field} from {old!r} to {new!r}."


async def _format_diff_llm(gemini, entity_kind: str, entity_id: str, field: str, old: Any, new: Any) -> str:
    # Quiet fallback when Gemini wasn't initialized (e.g. missing API key) — without
    # this guard every non-template edit logs a spurious "LLM diff format failed"
    # traceback because gemini.aio access raises AttributeError.
    if gemini is None:
        return _format_diff_template(entity_kind, entity_id, field, old, new)

    from google.genai import types
    label = _ENTITY_LABELS.get(entity_kind, entity_kind)
    prompt = (
        "Summarize this user edit in ONE short sentence as a clarifying statement "
        "the user just made about their finances. Keep it under 140 characters.\n\n"
        f"{label} {entity_id}: {field} changed from {old!r} to {new!r}."
    )
    try:
        resp = await gemini.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
        )
        text = (resp.text or "").strip()
        return text or _format_diff_template(entity_kind, entity_id, field, old, new)
    except Exception:
        logger.exception("LLM diff format failed; falling back to template")
        return _format_diff_template(entity_kind, entity_id, field, old, new)


def _find_existing_facts(db, *, user_id: UUID, entity_kind: str, entity_id: str, field: str) -> list[dict]:
    res = (
        db.table("user_notes")
        .select("id, provenance")
        .eq("user_id", str(user_id))
        .eq("kind", "fact")
        .is_("superseded_by", "null")
        .contains("tags", [f"entity:{entity_kind}:{entity_id}"])
        .execute()
    )
    rows = res.data or []
    # filter by provenance.field client-side (Supabase-py JSONB filtering varies)
    return [r for r in rows if (r.get("provenance") or {}).get("field") == field]


async def emit_fact_from_edit(
    *,
    db,
    gemini,
    user_id: UUID,
    entity_kind: str,
    entity_id: str,
    before: dict,
    after: dict,
    source_event: dict | None = None,
) -> None:
    """For each changed field, insert a fact note and mark prior fact about (entity,field) superseded.

    Best-effort: failures are logged and swallowed. Must not fail the user's edit.
    """
    try:
        diffs = _diff_fields(before, after)
        for field, old, new in diffs:
            if field in _TEMPLATE_FIELDS or isinstance(new, (int, float, bool)):
                content = _format_diff_template(entity_kind, entity_id, field, old, new)
            else:
                content = await _format_diff_llm(gemini, entity_kind, entity_id, field, old, new)

            importance = await score_importance(gemini, content, NoteKind.FACT)

            new_note = insert_note(db, NewNote(
                user_id=user_id,
                kind=NoteKind.FACT,
                content=content,
                tags=[f"entity:{entity_kind}:{entity_id}"],
                entity_refs={f"{entity_kind}s": [entity_id]},
                source=NoteSource.ENTITY_EDIT,
                importance=importance,
                provenance={
                    "field": field,
                    "before": old,
                    "after": new,
                    "source_event": source_event or {},
                },
            ))
            old_rows = _find_existing_facts(
                db, user_id=user_id, entity_kind=entity_kind, entity_id=entity_id, field=field,
            )
            old_ids = [UUID(r["id"]) for r in old_rows if r["id"] != str(new_note.id)]
            if old_ids:
                supersede_notes(db, old_ids=old_ids, new_id=new_note.id)
    except Exception:
        logger.exception("emit_fact_from_edit failed (entity=%s/%s)", entity_kind, entity_id)


_POSITIVE_LABELS = {"accurate_numbers", "on_topic", "good_advice", "helpful"}
_NEGATIVE_LABELS = {"inaccurate_numbers", "off_topic", "bad_advice", "not_helpful", "too_technical"}
_ALL_LABELS = _POSITIVE_LABELS | _NEGATIVE_LABELS

_EXCERPT_LIMIT = 400


def _excerpt(s: str, n: int = _EXCERPT_LIMIT) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _has_live_feedback_note(db, *, user_id: UUID, message_id: str, label: str) -> bool:
    """Return True if a non-superseded, non-expired feedback note exists for this triple.

    Used to keep True-toggles idempotent so rapid duplicate POSTs don't hit the
    partial unique index `idx_user_notes_feedback_dedup`.
    """
    res = (
        db.table("user_notes").select("id, provenance, expires_at")
        .eq("user_id", str(user_id))
        .eq("source", "message_feedback")
        .is_("superseded_by", "null")
        .is_("expires_at", "null")
        .execute()
    )
    for r in (res.data or []):
        prov = r.get("provenance") or {}
        if prov.get("message_id") == message_id and prov.get("label") == label:
            return True
    return False


def retire_existing_feedback_note(db, *, user_id: UUID, message_id: str, label: str) -> None:
    res = (
        db.table("user_notes").select("id, provenance")
        .eq("user_id", str(user_id))
        .eq("source", "message_feedback")
        .is_("superseded_by", "null")
        .is_("expires_at", "null")
        .execute()
    )
    matches = [
        r["id"] for r in (res.data or [])
        if (r.get("provenance") or {}).get("message_id") == message_id
        and (r.get("provenance") or {}).get("label") == label
    ]
    if not matches:
        return
    from app.notes.store import retire_note
    for rid in matches:
        retire_note(db, UUID(rid))


async def emit_from_feedback(
    *,
    db,
    gemini,
    user_id: UUID,
    message_id: str,
    session_id: str,
    user_message_text: str,
    assistant_message_text: str,
    labels: dict[str, bool],
) -> None:
    """Path 2 capture: each label set True becomes (or refreshes) an example note;
    each label set False retires the matching prior note (if any).

    Idempotent on True-toggles — if a live note already exists for
    (user, message, label), this is a no-op rather than a duplicate insert.

    Importance is scored via Gemini for each new note. Falls through to the
    default (5) if `gemini` is None or unreachable.
    """
    profile_tag = f"entity:profile:{user_id}"
    user_excerpt = _excerpt(user_message_text)
    asst_excerpt = _excerpt(assistant_message_text)

    for label, value in labels.items():
        if label not in _ALL_LABELS:
            continue
        if value:
            if _has_live_feedback_note(db, user_id=user_id, message_id=message_id, label=label):
                continue  # already recorded, no-op
            topic = "topic:advisor-confirmed" if label in _POSITIVE_LABELS else "topic:advisor-mistake"
            verb = "confirmed" if label in _POSITIVE_LABELS else "flagged"
            content = (
                f"User {verb} the advisor's reply was {label}.\n"
                f"Q: {user_excerpt}\n"
                f"A: {asst_excerpt}"
            )
            if label in {"helpful", "not_helpful", "too_technical"}:
                content = (
                    f"User rated the reply: {label}. This is a subjective experience signal, "
                    f"not verification of numerical accuracy or financial suitability.\n"
                    f"Q: {user_excerpt}\nA: {asst_excerpt}"
                )
            importance = await score_importance(gemini, content, NoteKind.EXAMPLE)
            insert_note(db, NewNote(
                user_id=user_id,
                kind=NoteKind.EXAMPLE,
                content=content,
                tags=[topic, profile_tag],
                source=NoteSource.MESSAGE_FEEDBACK,
                importance=importance,
                provenance={
                    "message_id": message_id,
                    "session_id": session_id,
                    "label": label,
                },
            ))
            from app.notes.compaction import prune_examples_for_pattern
            prune_examples_for_pattern(db, user_id=user_id, primary_tag=topic)
        else:
            retire_existing_feedback_note(
                db, user_id=user_id, message_id=message_id, label=label,
            )
