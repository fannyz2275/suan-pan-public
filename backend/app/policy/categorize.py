"""Categorization domain for the policy layer.

Promotion rule for categorize: when the user has corrected the same
normalized description to the same category at least PROMOTION_THRESHOLD
times (counting the current correction), write/reinforce a policy that
maps `description:<normalized>` -> {"category": <new_cat>}.

Apply path: at insert time (imports, plaid, manual), call `apply()` with
the about-to-be-saved category. If a policy exists for the normalized
description, return the override; otherwise return the default unchanged.

Both functions are best-effort. Failures fall through to default behavior
— a broken policy layer must never block a user write or import.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from app.engine.recurring.normalize import normalize_description
from app.policy import store as policy_store
from app.policy.schema import Domain

logger = logging.getLogger(__name__)

DOMAIN = Domain.CATEGORIZE

# Two-strike rule: the user must make the same desc -> category correction
# at least twice before the system promotes it to a sticky policy. Single
# corrections are usually one-offs; the second occurrence is the signal.
PROMOTION_THRESHOLD = 2

# Bound the per-correction lookup so a single derive_from_correction call
# can't degrade into a full table scan for a power user.
_TXN_SCAN_CAP = 1000


def _key_for(normalized: str) -> str:
    return f"description:{normalized}"


def _normalized_or_none(description: Optional[str]) -> Optional[str]:
    if not description:
        return None
    norm = normalize_description(description)
    return norm or None


def derive_from_correction(
    db, *, user_id: UUID | str, description: str, new_category: str,
) -> bool:
    """Inspect the user's correction history for this normalized description.
    If they've now categorized it as `new_category` at least PROMOTION_THRESHOLD
    times, write/reinforce the override. Returns True on promotion.

    Best-effort: any failure logs and returns False (the original correction
    succeeded — only the future-bias side effect is dropped).
    """
    norm = _normalized_or_none(description)
    if not norm:
        return False

    try:
        rows = (
            db.table("transactions").select("id, description, category")
            .eq("user_id", str(user_id))
            .eq("category", new_category)
            .limit(_TXN_SCAN_CAP)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("derive_from_correction: txn scan failed for user=%s", user_id)
        return False

    matching = sum(
        1 for r in rows
        if _normalized_or_none(r.get("description")) == norm
    )
    if matching < PROMOTION_THRESHOLD:
        return False

    try:
        policy_store.insert_or_reinforce(
            db,
            user_id=user_id, domain=DOMAIN, key=_key_for(norm),
            value={"category": new_category},
        )
    except Exception:
        logger.exception("derive_from_correction: policy write failed for user=%s", user_id)
        return False

    return True


def apply(
    db, *, user_id: UUID | str, description: str, default_category: Optional[str],
) -> Optional[str]:
    """Return the policy-overridden category for `description`, or
    `default_category` if no policy exists. Used at every categorization
    write site (imports, plaid, manual create) so the engine bends to
    each user without LLM-in-the-loop.

    Best-effort: returns `default_category` on any failure.
    """
    norm = _normalized_or_none(description)
    if not norm:
        return default_category
    try:
        override = policy_store.lookup(
            db, user_id=user_id, domain=DOMAIN, key=_key_for(norm),
        )
    except Exception:
        logger.exception("policy.categorize.apply: lookup failed for user=%s", user_id)
        return default_category
    if override is None:
        return default_category
    return override.value.get("category", default_category)
