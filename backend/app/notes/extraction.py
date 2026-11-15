"""5-min-idle chat extraction loop. See spec §Path 3 — Conversational extraction."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, NAMESPACE_URL, uuid5

from app.notes.embed import embed_text
from app.notes.importance import score_importance
from app.notes.schema import NewNote, NoteKind, NoteSource
from app.notes.store import insert_note, similarity_search

logger = logging.getLogger(__name__)

IDLE_MINUTES = 5
MAX_MESSAGES_PER_RUN = 50
PREFERENCE_SIMILARITY_THRESHOLD = 0.85

_PROMPT_TEMPLATE = """You are extracting durable user knowledge from a financial chat.

Read the messages below and emit JSON with four arrays:

- "facts": ground-truth statements about specific entities the user identified
  (e.g., "user clarified account X is joint with spouse"). Skip anything already
  in the context. Each fact may include "entity_kind" and "entity_id" if known.
- "preferences": stances, values, policies, or rules the user expressed that
  should bias future advice (e.g., "won't tap 401k early"). Each must include
  "tags" — short topical tags (retirement, dining, debt, kids, etc.).
- "examples": specific corrections to advisor reasoning or classifications.
- "forecast_events": future planned consumption expenses explicitly expressed by
  the USER, not hypothetical suggestions from the assistant. Each has label,
  amount (remaining unpaid cost, or null if unknown), month (YYYY-MM or null),
  goal_id (only if explicitly known), existing_event_id (from context when updating),
  new_event (true only for a distinct new event), cancelled (true if cancelled),
  and source_quote (an exact user quote).
  Reuse the same concise label when updating an existing plan. Do not put account
  balances, savings targets, investment transfers or debt repayments here.
  Dates may be resolved from the reference date; never invent a missing cost or
  date. These events are automatically included in editable forecasts.

Rules:
- Emit nothing for chitchat, questions, or one-off observations.
- A statement must be DURABLE (likely true 3 months from now) to qualify as a preference.
- Do not invent. If unsure whether something belongs, skip it.
- NEVER extract dollar amounts, account balances, or net worth figures as facts or preferences — those live in Tier 2 live state and will be stale within days.
- The forecast_events array is the sole exception for future planned expenses.
- Output JSON only, no other text.

Examples:
  User: "I never want to touch my 401k early, even in a pinch."
  → preferences: [{{"content": "User won't withdraw from 401k before retirement", "tags": ["retirement"]}}]

  User: "My Chase account is joint with my spouse."
  → facts: [{{"content": "Chase checking is a joint account with spouse", "entity_kind": "account", "entity_id": null}}]

  User: "I spent $3,200 last month on dining."
  → skip entirely (dollar amount, ephemeral, already in Tier 2)

  User: "Thanks, that makes sense."
  → skip (chitchat)

CONTEXT (already known about this user, do not duplicate):
{context_summary}

REFERENCE DATE: {reference_date}

MESSAGES (oldest first):
{messages}
"""


def _build_prompt(*, context_summary: str, messages: list[dict]) -> str:
    msg_block = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    return _PROMPT_TEMPLATE.format(
        context_summary=context_summary or "(none)",
        messages=msg_block,
        reference_date=datetime.now(timezone.utc).date().isoformat(),
    )


def _load_recent_messages(db, user_id: UUID, since: Optional[datetime]) -> list[dict]:
    sess = db.table("chat_sessions").select("id").eq("user_id", str(user_id)).execute().data
    if not sess:
        return []
    sess_ids = [s["id"] for s in sess]
    q = (
        db.table("chat_messages").select("role,content,created_at")
        .in_("session_id", sess_ids)
        .order("created_at", desc=False)
        .limit(MAX_MESSAGES_PER_RUN)
    )
    if since:
        q = q.gt("created_at", since.isoformat())
    return q.execute().data or []


def _load_context_summary(db, user_id: UUID) -> str:
    """Tiny summary of high-strength prefs + recent facts, fed back as 'do not duplicate'."""
    res = (
        db.table("user_notes").select("content")
        .eq("user_id", str(user_id))
        .eq("kind", "preference")
        .gte("strength", 3)
        .is_("superseded_by", "null")
        .limit(20)
        .execute()
    )
    prefs = [r["content"] for r in (res.data or [])]
    res2 = (
        db.table("user_notes").select("content")
        .eq("user_id", str(user_id))
        .eq("kind", "fact")
        .is_("superseded_by", "null")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )
    facts = [r["content"] for r in (res2.data or [])]
    return "\n".join([*(f"pref: {p}" for p in prefs), *(f"fact: {f}" for f in facts)])


def _update_last_extracted(db, user_id: UUID) -> None:
    db.table("profiles").update(
        {"notes_last_extracted_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", str(user_id)).execute()


async def extract_for_user(*, db, gemini, user_id: UUID) -> int:
    """Run extraction once for one user. Returns the number of notes inserted/updated.

    Idempotent: failure mid-run leaves notes_last_extracted_at un-updated; next tick retries.
    """
    from google.genai import types

    profile = (
        db.table("profiles").select("notes_last_extracted_at")
        .eq("id", str(user_id)).limit(1).execute().data
    )
    last_ts = None
    raw_ts = profile[0].get("notes_last_extracted_at") if profile else None
    if isinstance(raw_ts, str) and raw_ts:
        last_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))

    msgs = _load_recent_messages(db, user_id, last_ts)
    if not msgs:
        return 0

    ctx = _load_context_summary(db, user_id) + _load_forecast_context(db, user_id)
    prompt = _build_prompt(context_summary=ctx, messages=msgs)

    try:
        resp = await gemini.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads(resp.text or "{}")
    except Exception:
        logger.exception("extract_for_user: Gemini call failed for user %s", user_id)
        return 0

    inserted = 0
    inserted += await _ingest_facts(db, gemini, user_id, data.get("facts", []) or [])
    inserted += await _ingest_preferences(db, gemini, user_id, data.get("preferences", []) or [])
    inserted += await _ingest_examples(db, gemini, user_id, data.get("examples", []) or [])
    inserted += _ingest_forecast_events(db, user_id, data.get('forecast_events', []) or [], msgs)

    _update_last_extracted(db, user_id)
    return inserted


def _ingest_forecast_events(db, user_id, items, messages) -> int:
    from app.engine.forecast import Assumption, event_key
    user_texts = [m['content'] for m in messages if m['role'] == 'user']
    count = 0
    existing = db.table('user_notes').select('id,provenance').eq('user_id', str(user_id)).execute().data or []
    existing = [n for n in existing if (n.get('provenance') or {}).get('forecast_event')]
    for item in items:
        quote = item.get('source_quote')
        if not isinstance(quote, str) or not quote.strip() or not any(quote in text for text in user_texts):
            continue
        label = item.get('label')
        if not isinstance(label, str) or not label.strip():
            continue
        key = event_key(label)
        target = next((n for n in existing if n['id'] == item.get('existing_event_id')), None)
        if item.get('existing_event_id') and target is None:
            continue
        matches = [n for n in existing if event_key(n['provenance']['forecast_event'].get('label', '')) == key]
        if target is None and not item.get('new_event') and len(matches) == 1:
            target = matches[0]
        previous = target['provenance']['forecast_event'] if target else {}
        try:
            event = Assumption(id=f'memory:{key}', label=label[:120], group='planned_spending',
                               source='memory', frequency='once',
                               amount=item.get('amount') if item.get('amount') is not None else previous.get('amount'),
                               month=item.get('month') or previous.get('month'))
        except ValueError:
            continue
        payload = {
            'id':target['id'] if target else str(uuid5(NAMESPACE_URL, f'suan-pan:{user_id}:forecast-event:{key}:{quote}')),
            'user_id':str(user_id), 'kind':'fact', 'source':'chat_extraction',
            'content':f'Planned expense: {event.label}. {quote}',
            'tags':['topic:forecast'], 'entity_refs':{}, 'importance':5,
            'provenance':{'forecast_event':{'label':event.label, 'amount':event.amount,
                          'month':event.month, 'goal_id':item.get('goal_id') or previous.get('goal_id'),
                          'new_event':item.get('new_event', previous.get('new_event', False)),
                          'cancelled':item.get('cancelled', previous.get('cancelled', False))}, 'source_quote':quote},
        }
        db.table('user_notes').upsert(payload).execute()
        existing = [n for n in existing if n['id'] != payload['id']] + [payload]
        count += 1
    return count


def _load_forecast_context(db, user_id) -> str:
    goals = db.table('goals').select('id,name,type,target_amount,target_date').eq('user_id', str(user_id)).eq('is_active', True).execute().data or []
    notes = db.table('user_notes').select('id,provenance').eq('user_id', str(user_id)).execute().data or []
    events = [{'existing_event_id':n['id'], **n['provenance']['forecast_event']} for n in notes
              if (n.get('provenance') or {}).get('forecast_event')]
    return '\nEXISTING GOALS (link goal_id; do not duplicate):\n' + json.dumps(goals) + '\nEXISTING FORECAST EVENTS (use existing_event_id for changes/cancellation):\n' + json.dumps(events)


async def _ingest_facts(db, gemini, user_id: UUID, items: list[dict]) -> int:
    n = 0
    for item in items:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        ekind = item.get("entity_kind")
        eid = item.get("entity_id")
        tags = []
        entity_refs: dict = {}
        if ekind and eid:
            tags.append(f"entity:{ekind}:{eid}")
            entity_refs = {f"{ekind}s": [eid]}
        importance = await score_importance(gemini, content, NoteKind.FACT)
        insert_note(db, NewNote(
            user_id=user_id, kind=NoteKind.FACT, content=content,
            tags=tags, entity_refs=entity_refs,
            source=NoteSource.CHAT_EXTRACTION,
            importance=importance,
        ))
        n += 1
    return n


async def _ingest_preferences(db, gemini, user_id: UUID, items: list[dict]) -> int:
    n = 0
    for item in items:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        tag_slugs = item.get("tags") or []
        tags = [f"topic:{s}" for s in tag_slugs if isinstance(s, str)]

        emb = await embed_text(gemini, content)
        if emb is not None:
            existing = similarity_search(
                db, user_id=user_id, query_vec=emb, kind="preference",
                limit=1, threshold=PREFERENCE_SIMILARITY_THRESHOLD,
            )
            if existing:
                # Bump strength on the existing row instead of inserting a duplicate
                target = existing[0]
                db.table("user_notes").update({
                    "strength": (target.strength or 1) + 1,
                }).eq("id", str(target.id)).execute()
                n += 1
                continue

        importance = await score_importance(gemini, content, NoteKind.PREFERENCE)
        insert_note(db, NewNote(
            user_id=user_id, kind=NoteKind.PREFERENCE, content=content,
            tags=tags, embedding=emb,
            source=NoteSource.CHAT_EXTRACTION,
            importance=importance,
        ))
        n += 1
    return n


async def _ingest_examples(db, gemini, user_id: UUID, items: list[dict]) -> int:
    n = 0
    for item in items:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        tags = [f"topic:{s}" for s in (item.get("tags") or []) if isinstance(s, str)]
        emb = await embed_text(gemini, content)
        importance = await score_importance(gemini, content, NoteKind.EXAMPLE)
        insert_note(db, NewNote(
            user_id=user_id, kind=NoteKind.EXAMPLE, content=content,
            tags=tags, embedding=emb,
            source=NoteSource.CHAT_EXTRACTION,
            importance=importance,
        ))
        n += 1
    return n


import asyncio


async def tick(*, db_factory, gemini) -> int:
    """Run one tick of the extraction loop. Returns total notes ingested across users.

    Find users whose most recent message is > IDLE_MINUTES old AND newer than their
    notes_last_extracted_at, then run extract_for_user for each (under an advisory lock).
    """
    if gemini is None:
        from app.provider_credentials.crypto import keyring, CredentialError
        try:
            keyring()
        except CredentialError:
            return 0
    db = db_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=IDLE_MINUTES)

    # Candidate users: anyone with messages newer than their last extraction AND
    # whose most-recent message is older than the cutoff.
    res = db.rpc("notes_eligible_users_for_extraction", {
        "p_idle_cutoff": cutoff.isoformat(),
    }).execute()
    user_ids = [UUID(r["user_id"]) for r in (res.data or [])]

    total = 0
    for uid in user_ids:
        # Postgres advisory lock keyed on a hash of user_id to prevent concurrent runs.
        lock_key = hash(str(uid)) & 0x7FFFFFFF
        try:
            got = db.rpc("notes_try_advisory_lock", {"p_key": lock_key}).execute()
            got_lock = got.data is True or got.data == [True]
        except Exception:
            logger.exception("tick: advisory lock attempt failed for %s; skipping", uid)
            continue
        if not got_lock:
            continue
        try:
            from app.provider_credentials.scope import credential_scope, gemini_client
            async with credential_scope(uid):
                user_gemini = gemini if gemini is not None else gemini_client(optional=True)
                if user_gemini is None:
                    continue
                total += await extract_for_user(db=db, gemini=user_gemini, user_id=uid)

                # Daily preference merge — at most once per 24h per user
                last_merge = (
                    db.table("profiles").select("notes_last_merged_at").eq("id", str(uid))
                    .limit(1).execute().data
                )
                last_raw = last_merge[0].get("notes_last_merged_at") if last_merge else None
                should_merge = True
                if last_raw and isinstance(last_raw, str):
                    try:
                        last_dt = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
                        if (datetime.now(timezone.utc) - last_dt) < timedelta(hours=24):
                            should_merge = False
                    except Exception:
                        pass  # malformed timestamp — proceed with merge
                if should_merge:
                    try:
                        from app.notes.compaction import merge_preferences_for_user
                        await merge_preferences_for_user(db=db, gemini=user_gemini, user_id=uid)
                        db.table("profiles").update({
                            "notes_last_merged_at": datetime.now(timezone.utc).isoformat()
                        }).eq("id", str(uid)).execute()
                    except Exception:
                        logger.exception("nightly merge failed for %s", uid)
        except Exception:
            logger.exception("tick: extract_for_user failed for %s", uid)
        finally:
            try:
                db.rpc("notes_advisory_unlock", {"p_key": lock_key}).execute()
            except Exception:
                logger.exception("tick: advisory unlock failed for %s", uid)
    return total


async def run_loop(*, db_factory, gemini, stop_event: asyncio.Event) -> None:
    """Lifespan-bound asyncio task. Ticks every 60s until stop_event is set."""
    while not stop_event.is_set():
        try:
            await tick(db_factory=db_factory, gemini=gemini)
        except Exception:
            logger.exception("extraction tick crashed; continuing")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            pass
