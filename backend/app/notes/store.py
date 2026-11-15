"""DB helpers for user_notes.

Tier 3 retrieval orchestration lives here (`retrieve_scored`); the pure
algorithmic pieces (constants + scoring/MMR helpers) live in
`app.notes.scoring`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.notes.schema import DEFAULT_IMPORTANCE, NewNote, Note, ScoredNote
from app.notes.scoring import (
    DEFAULT_POOL_N,
    DEFAULT_TOP_K,
    MMR_LAMBDA,
    TAG_BOOST_CAP,
    W_IMPORTANCE,
    W_RECENCY,
    W_RELEVANCY,
    compute_raw_scores,
    min_max_normalize,
    mmr_select,
)

logger = logging.getLogger(__name__)


def _format_embedding(vec: Optional[list[float]]) -> Optional[str]:
    """pgvector accepts the text wire format `"[0.1,0.2,...]"`, not a JSON array.

    PostgREST receives our payload as JSON; a JSON array won't implicitly cast to
    `vector` on the Postgres side. Serialize to the bracket-text format here.
    """
    if vec is None:
        return None
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def insert_note(db, new: NewNote) -> Note:
    payload = {
        "user_id": str(new.user_id),
        "kind": new.kind.value,
        "content": new.content,
        "tags": new.tags,
        "entity_refs": new.entity_refs,
        "embedding": _format_embedding(new.embedding),
        "source": new.source.value,
        "provenance": new.provenance,
        "strength": new.strength,
        "importance": new.importance if new.importance is not None else DEFAULT_IMPORTANCE,
        "expires_at": new.expires_at.isoformat() if new.expires_at else None,
    }
    res = db.table("user_notes").insert(payload).execute()
    row = res.data[0]
    return _row_to_note(row)


def get_note(db, note_id: UUID) -> Optional[Note]:
    res = db.table("user_notes").select("*").eq("id", str(note_id)).limit(1).execute()
    rows = res.data or []
    if not rows:
        return None
    return _row_to_note(rows[0])


def retire_note(db, note_id: UUID) -> None:
    """Set expires_at = now() so the row is excluded from retrieval but kept for audit."""
    now = datetime.now(timezone.utc).isoformat()
    db.table("user_notes").update({"expires_at": now}).eq("id", str(note_id)).execute()


def supersede_notes(db, *, old_ids: list[UUID], new_id: UUID) -> None:
    """Mark each old row as superseded by new_id, and append old_ids to new_id.supersedes."""
    if not old_ids:
        return
    new_id_str = str(new_id)
    # Update old rows
    for oid in old_ids:
        db.table("user_notes").update({"superseded_by": new_id_str}).eq("id", str(oid)).execute()
    # Update new row's supersedes array
    res = db.table("user_notes").select("supersedes").eq("id", new_id_str).execute()
    current = (res.data[0]["supersedes"] or []) if res.data else []
    merged = list({*current, *(str(x) for x in old_ids)})
    db.table("user_notes").update({"supersedes": merged}).eq("id", new_id_str).execute()


def similarity_search(
    db,
    *,
    user_id: UUID,
    query_vec: list[float],
    kind: str = "preference",
    limit: int = 8,
    threshold: float = 0.7,
) -> list[Note]:
    """Top-K notes by cosine similarity to query_vec, filtered by kind, RLS-respecting."""
    res = db.rpc(
        "match_user_notes",
        {
            "p_user_id": str(user_id),
            "p_query": _format_embedding(query_vec),
            "p_kind": kind,
            "p_limit": limit,
            "p_threshold": threshold,
        },
    ).execute()
    rows = res.data or []
    # The RPC returns a subset of columns; fill the rest with defaults so Note validates.
    out = []
    for r in rows:
        out.append(Note(
            id=r["id"],
            user_id=user_id,
            kind=kind,
            content=r["content"],
            tags=r.get("tags") or [],
            entity_refs=r.get("entity_refs") or {},
            embedding=None,
            source=r["source"],
            provenance=r.get("provenance") or {},
            strength=r.get("strength") or 1,
            supersedes=[],
            superseded_by=None,
            expires_at=None,
            created_at=datetime.now(timezone.utc),  # not returned; not used downstream
        ))
    return out


HIGH_STRENGTH = 3
PREFERENCE_CAP = 10
EXAMPLE_CAP_TOTAL = 8
EXAMPLE_CAP_PER_TAG = 3
HARD_TOTAL_CAP = 25


def retrieve_notes(
    db,
    *,
    user_id: UUID,
    scope_tags: list[str],
    query_text: Optional[str],
    query_vec: Optional[list[float]] = None,
    limit: int = HARD_TOTAL_CAP,
) -> list[Note]:
    """Hybrid retrieval. See spec §Retrieval for algorithm.

    `query_vec` is provided by the caller (advisor route) to avoid embedding
    the same text twice; if None and query_text is set, the caller is responsible
    for embedding upstream — this function only uses pre-computed vectors.
    """
    facts = _fetch_facts(db, user_id=user_id, scope_tags=scope_tags)
    prefs = _fetch_preferences(
        db, user_id=user_id, scope_tags=scope_tags, query_vec=query_vec,
    )
    examples = _fetch_examples(db, user_id=user_id, scope_tags=scope_tags)

    out = facts + prefs + examples
    if len(out) <= limit:
        return out

    # Truncate: drop oldest examples first, then lowest-strength prefs, never facts.
    keep_facts = facts
    over = len(out) - limit
    examples_sorted = sorted(examples, key=lambda n: n.created_at, reverse=True)
    drop_examples = max(0, min(over, len(examples_sorted)))
    examples_kept = examples_sorted[: len(examples_sorted) - drop_examples]
    over -= drop_examples
    if over > 0:
        prefs_sorted = sorted(prefs, key=lambda n: n.strength, reverse=True)
        prefs_kept = prefs_sorted[: max(0, len(prefs_sorted) - over)]
    else:
        prefs_kept = prefs
    return keep_facts + prefs_kept + examples_kept


def _fetch_facts(db, *, user_id: UUID, scope_tags: list[str]) -> list[Note]:
    if not scope_tags:
        return []
    res = (
        db.table("user_notes")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("kind", "fact")
        .is_("superseded_by", "null")
        .overlaps("tags", scope_tags)
        .execute()
    )
    rows = [r for r in (res.data or []) if not _is_expired(r)]
    return [_row_to_note(r) for r in rows]


def _fetch_preferences(
    db, *, user_id: UUID, scope_tags: list[str], query_vec: Optional[list[float]]
) -> list[Note]:
    by_id: dict[str, Note] = {}

    # (a) High-strength always-inject
    res = (
        db.table("user_notes")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("kind", "preference")
        .is_("superseded_by", "null")
        .gte("strength", HIGH_STRENGTH)
        .execute()
    )
    for r in (res.data or []):
        if not _is_expired(r):
            by_id[r["id"]] = _row_to_note(r)

    # (b) Tag-matched
    if scope_tags:
        res = (
            db.table("user_notes")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("kind", "preference")
            .is_("superseded_by", "null")
            .overlaps("tags", scope_tags)
            .execute()
        )
        for r in (res.data or []):
            if not _is_expired(r):
                by_id[r["id"]] = _row_to_note(r)

    # (c) Embedding-matched
    if query_vec is not None:
        hits = similarity_search(
            db, user_id=user_id, query_vec=query_vec, kind="preference",
            limit=8, threshold=0.7,
        )
        for h in hits:
            by_id[str(h.id)] = h

    out = list(by_id.values())
    if len(out) > PREFERENCE_CAP:
        out.sort(key=lambda n: n.strength, reverse=True)
        out = out[:PREFERENCE_CAP]
    return out


def _fetch_examples(db, *, user_id: UUID, scope_tags: list[str]) -> list[Note]:
    if not scope_tags:
        return []
    res = (
        db.table("user_notes")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("kind", "example")
        .is_("superseded_by", "null")
        .overlaps("tags", scope_tags)
        .order("created_at", desc=True)
        .execute()
    )
    rows = [r for r in (res.data or []) if not _is_expired(r)]
    # Group by primary (non-profile) tag and cap per group
    by_tag: dict[str, list[dict]] = {}
    for r in rows:
        primary = next(
            (t for t in (r.get("tags") or []) if not t.startswith("entity:profile:")),
            "_other",
        )
        by_tag.setdefault(primary, []).append(r)
    kept: list[dict] = []
    for tag, group in by_tag.items():
        kept.extend(group[:EXAMPLE_CAP_PER_TAG])
    kept.sort(key=lambda r: r["created_at"], reverse=True)
    return [_row_to_note(r) for r in kept[:EXAMPLE_CAP_TOTAL]]


def _is_expired(row: dict) -> bool:
    exp = row.get("expires_at")
    if not exp:
        return False
    return datetime.fromisoformat(exp.replace("Z", "+00:00")) <= datetime.now(timezone.utc)


# ---- Scored retrieval ------------------------------------------------------


def retrieve_scored(
    db,
    *,
    user_id: UUID,
    query_vec: Optional[list[float]],
    scope_tags: Optional[list[str]] = None,
    pool_n: int = DEFAULT_POOL_N,
    top_k: int = DEFAULT_TOP_K,
    exclude_ids: Optional[list[UUID]] = None,
    now: Optional[datetime] = None,
) -> list[ScoredNote]:
    """Tier 3 retrieval: scored + MMR-reranked top-K notes for the user.

    Returns up to `top_k` ScoredNotes, ordered by final descending score,
    with the K returned rows' `last_accessed_at` bumped to `now()` so future
    recency math reflects this access. Caller passes `query_vec` (already
    embedded) to avoid embedding the same text twice across the turn.

    Falls through to an empty list on:
      - missing query_vec AND missing scope_tags
      - empty candidate pool
      - any DB error (logged)

    The function never raises — Tier 3 is enrichment; the chat must work
    even if memory retrieval is unavailable.
    """
    now = now or datetime.now(timezone.utc)
    exclude_set = {str(x) for x in (exclude_ids or [])}

    try:
        candidates = _build_candidate_pool(
            db, user_id=user_id, query_vec=query_vec,
            scope_tags=scope_tags or [], pool_n=pool_n,
        )
    except Exception:
        logger.exception("retrieve_scored: candidate fetch failed")
        return []

    candidates = [c for c in candidates if str(c["id"]) not in exclude_set]
    if not candidates:
        return []

    raw_scores = [compute_raw_scores(c, query_vec, now) for c in candidates]
    normed = min_max_normalize(raw_scores)
    summed = [
        W_RELEVANCY * n["rel"] + W_RECENCY * n["rec"] + W_IMPORTANCE * n["imp"]
        for n in normed
    ]

    paired = sorted(
        zip(candidates, raw_scores, summed),
        key=lambda t: -t[2],
    )

    selected_idx = mmr_select(
        ordered=paired, query_vec=query_vec, top_k=top_k, lam=MMR_LAMBDA,
    )

    out: list[ScoredNote] = []
    for idx in selected_idx:
        cand, raw, score = paired[idx]
        out.append(ScoredNote(
            note=_row_to_note(cand),
            raw_relevancy=raw["rel"],
            raw_recency=raw["rec"],
            raw_importance=raw["imp"],
            score=score,
        ))

    if out:
        try:
            # Scope by user_id too — backend uses service-role which bypasses
            # RLS, so the .in_(id) filter alone is not a security boundary.
            db.table("user_notes").update(
                {"last_accessed_at": now.isoformat()}
            ).eq("user_id", str(user_id)).in_(
                "id", [str(s.note.id) for s in out]
            ).execute()
        except Exception:
            # Access-time bump is best-effort; a failed update only weakens
            # future recency, never breaks the current turn.
            logger.exception("retrieve_scored: last_accessed_at bump failed")

    return out


def _build_candidate_pool(
    db, *, user_id: UUID, query_vec: Optional[list[float]],
    scope_tags: list[str], pool_n: int,
) -> list[dict]:
    """Union of (a) top-N by pgvector cosine and (b) up to TAG_BOOST_CAP rows
    matching any scope_tag — capped, deduped on id, embeddings preserved."""
    by_id: dict[str, dict] = {}

    if query_vec is not None:
        res = db.rpc(
            "match_user_notes_scored",
            {
                "p_user_id": str(user_id),
                "p_query": _format_embedding(query_vec),
                "p_limit": pool_n,
            },
        ).execute()
        for r in (res.data or []):
            by_id[str(r["id"])] = r

    if scope_tags:
        res = (
            db.table("user_notes")
            .select("*")
            .eq("user_id", str(user_id))
            .is_("superseded_by", "null")
            .overlaps("tags", scope_tags)
            .limit(TAG_BOOST_CAP + pool_n)  # generous; we dedupe + cap below
            .execute()
        )
        added = 0
        for r in (res.data or []):
            if added >= TAG_BOOST_CAP:
                break
            if _is_expired(r):
                continue
            if str(r["id"]) in by_id:
                continue
            # Boost candidates from tag-only path don't carry a cosine; we
            # supply 0.0 so the pool's min-max normalization treats them as
            # the floor of the relevancy axis (their recency/importance can
            # still pull them into the top-K via the other terms).
            r.setdefault("cosine_similarity", 0.0)
            by_id[str(r["id"])] = r
            added += 1

    return list(by_id.values())




def _row_to_note(row: dict) -> Note:
    """Coerce a Supabase row dict into a Note."""
    # vector column comes back as a string like "[0.1,0.2,...]" or as list depending on driver
    emb = row.get("embedding")
    if isinstance(emb, str):
        emb = json.loads(emb)
    return Note(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        content=row["content"],
        tags=row.get("tags") or [],
        entity_refs=row.get("entity_refs") or {},
        embedding=emb,
        source=row["source"],
        provenance=row.get("provenance") or {},
        strength=row.get("strength") or 1,
        # Tolerate rows from a DB that hasn't run M0.2 yet.
        importance=row.get("importance") if row.get("importance") is not None else DEFAULT_IMPORTANCE,
        last_accessed_at=row.get("last_accessed_at"),
        supersedes=row.get("supersedes") or [],
        superseded_by=row.get("superseded_by"),
        expires_at=row.get("expires_at"),
        created_at=row["created_at"],
    )
