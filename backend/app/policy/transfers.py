"""Transfers domain for the policy layer.

Promotion rule for transfers: a single explicit `mark_external` action is
enough to write a policy. The user is asserting "this kind of transaction
is external — never try to pair it with internal flows again." Higher
threshold than categorize because the action is more deliberate and the
cost of over-correction (re-pairing something the user already excluded)
is annoying enough to warrant immediate stickiness.

`dismiss` does NOT write a policy in v1 — it can mean either "this
specific txn isn't a transfer" (per-row signal, no policy) or "all txns
matching this description aren't transfers" (per-pattern signal, would
write policy). Without a UI to disambiguate, we conservatively treat
dismiss as the per-row case. Promotion-on-dismiss can land in a later PR
with a higher threshold (e.g., 3 dismissals of the same description).

Apply path: at `detect_pairs_and_orphans` time, filter out candidate
transactions whose normalized description matches a `external:<norm>`
policy. They never enter the pairing pool, so the user doesn't have to
re-dismiss them.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional
from uuid import UUID

from app.engine.recurring.normalize import normalize_description
from app.policy import store as policy_store
from app.policy.schema import Domain

logger = logging.getLogger(__name__)

DOMAIN = Domain.TRANSFERS


def _key_for_external(normalized: str) -> str:
    return f"external:{normalized}"


def _normalized_or_none(description: Optional[str]) -> Optional[str]:
    if not description:
        return None
    norm = normalize_description(description)
    return norm or None


def derive_from_mark_external(
    db, *, user_id: UUID | str, description: str,
) -> bool:
    """Write/reinforce an `external:<normalized>` policy. Returns True on
    successful write, False on any failure (mark_external itself succeeded
    upstream — only the side effect drops)."""
    norm = _normalized_or_none(description)
    if not norm:
        return False
    try:
        policy_store.insert_or_reinforce(
            db,
            user_id=user_id, domain=DOMAIN, key=_key_for_external(norm),
            value={"always_external": True},
        )
        return True
    except Exception:
        logger.exception(
            "policy.transfers.derive_from_mark_external failed for user=%s", user_id,
        )
        return False


def filter_external_candidates(
    db, *, user_id: UUID | str, candidates: Iterable[dict],
) -> list[dict]:
    """Return `candidates` with any txn marked-external-by-policy removed.

    Best-effort: on lookup failure returns the input unchanged (engine
    falls back to unbiased pairing rather than 500ing).
    """
    candidates = list(candidates)
    if not candidates:
        return candidates

    # One DB read for the user's transfers policies, then filter in-process.
    # Avoids N lookups for N candidates in the same detection pass.
    try:
        external_keys = {
            o.key for o in policy_store.list_for_user(
                db, user_id=user_id, domain=DOMAIN,
            )
            if o.value.get("always_external") is True
        }
    except Exception:
        logger.exception(
            "policy.transfers.filter_external_candidates: lookup failed for user=%s",
            user_id,
        )
        return candidates

    if not external_keys:
        return candidates

    out: list[dict] = []
    for c in candidates:
        norm = _normalized_or_none(c.get("description"))
        if norm and _key_for_external(norm) in external_keys:
            continue
        out.append(c)
    return out
