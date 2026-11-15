"""Compaction loops: example pruning + nightly preference merge."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.notes.embed import embed_text
from app.notes.schema import NewNote, NoteKind, NoteSource
from app.notes.store import insert_note, supersede_notes

logger = logging.getLogger(__name__)

EXAMPLE_CAP_PER_TAG = 8


def prune_examples_for_pattern(db, *, user_id: UUID, primary_tag: str, cap: int = EXAMPLE_CAP_PER_TAG) -> int:
    """Mark oldest examples in a (user, primary_tag) group as expired once count > cap.

    Returns the number pruned. Uses expires_at = now() to retire (consistent with retire_note).
    """
    res = (
        db.table("user_notes").select("id,created_at")
        .eq("user_id", str(user_id)).eq("kind", "example")
        .is_("superseded_by", "null")
        .is_("expires_at", "null")
        .contains("tags", [primary_tag])
        .order("created_at", desc=True)
        .execute()
    )
    rows = res.data or []
    if len(rows) <= cap:
        return 0
    to_prune = rows[cap:]
    now = datetime.now(timezone.utc).isoformat()
    for r in to_prune:
        db.table("user_notes").update({"expires_at": now}).eq("id", r["id"]).execute()
    return len(to_prune)


_MERGE_PROMPT = """You are merging a user's stated preferences into a canonical list.

Rules:
- Combine near-duplicates (same stance worded differently) into ONE canonical statement.
- On contradictions, keep the most recent and discard older.
- Preserve specificity — do not over-generalize.
- For each output preference, list the input ids it supersedes in "supersedes".
- Output JSON only with shape {{"preferences": [{{"content", "tags", "strength", "supersedes"}}]}}

INPUT PREFERENCES:
{prefs_json}
"""


async def merge_preferences_for_user(*, db, gemini, user_id: UUID, min_count: int = 2) -> int:
    """Run the merge prompt over all live preferences for the user.

    Returns the number of new merged rows inserted. Returns 0 when below threshold
    or on any failure.
    """
    from google.genai import types
    res = (
        db.table("user_notes").select("id,content,tags,strength")
        .eq("user_id", str(user_id)).eq("kind", "preference")
        .is_("superseded_by", "null")
        .execute()
    )
    rows = [r for r in (res.data or []) if 'engine:forecast-settings' not in (r.get('tags') or [])]
    if len(rows) < min_count:
        return 0

    prefs_in = [
        {"id": r["id"], "content": r["content"], "tags": r.get("tags") or [], "strength": r.get("strength") or 1}
        for r in rows
    ]
    prompt = _MERGE_PROMPT.format(prefs_json=json.dumps(prefs_in, ensure_ascii=False, indent=2))

    try:
        resp = await gemini.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads(resp.text or "{}")
    except Exception:
        logger.exception("merge_preferences_for_user: Gemini call failed for %s", user_id)
        return 0

    out_prefs = data.get("preferences") or []
    inserted = 0
    for p in out_prefs:
        content = (p.get("content") or "").strip()
        if not content:
            continue
        tag_slugs = [t for t in (p.get("tags") or []) if isinstance(t, str)]
        tags = [s if s.startswith("topic:") else f"topic:{s}" for s in tag_slugs]
        strength = int(p.get("strength") or 1)
        supersedes_raw = [x for x in (p.get("supersedes") or []) if isinstance(x, str)]
        # Convert to UUIDs where possible; keep raw strings for provenance
        supersedes_ids: list[UUID] = []
        for x in supersedes_raw:
            try:
                supersedes_ids.append(UUID(x))
            except (ValueError, AttributeError):
                pass  # non-UUID ids (e.g. in tests) are skipped for type-safe calls

        emb = await embed_text(gemini, content)
        new_note = insert_note(db, NewNote(
            user_id=user_id, kind=NoteKind.PREFERENCE, content=content,
            tags=tags, embedding=emb, strength=strength,
            source=NoteSource.COMPACTION_MERGE,
            provenance={"merged_from": supersedes_raw},
        ))
        if supersedes_raw:
            # Pass UUIDs if we have them; fall back to raw strings for monkeypatched environments
            ids_to_pass: list = supersedes_ids if supersedes_ids else supersedes_raw  # type: ignore[assignment]
            supersede_notes(db, old_ids=ids_to_pass, new_id=new_note.id)
        inserted += 1
    return inserted
