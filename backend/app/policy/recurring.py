"""Recurring-detection domain for the policy layer.

Two related signals from the recurring rule lifecycle:

  user_rejected  — user explicitly said "this is not a recurring rule".
                   Detection should never re-propose the same normalized
                   keyword again. Single rejection is enough — the user
                   already took explicit action.

  user_confirmed — user explicitly said "yes this is a recurring rule".
                   Today the recurring detector ALREADY uses confirmed
                   rules as few-shot examples (see
                   engine/recurring/llm.py::llm_refine_cluster). Adding
                   a redundant policy row would be extra writes for no
                   gain, so PR #1 only writes for rejections. The
                   confirmed-rule signal stays implicit in the
                   recurring_rules table itself.

Apply path: at `detect_recurring_rules` time, filter out candidate
clusters whose normalized keyword matches a `reject:<keyword>` policy.
The clusters never reach the LLM tiebreaker or the user's review queue,
so the user doesn't have to re-reject the same suggestion.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional
from uuid import UUID

from app.engine.recurring.normalize import normalize_description
from app.policy import store as policy_store
from app.policy.schema import Domain

logger = logging.getLogger(__name__)

DOMAIN = Domain.RECURRING


def _key_for_rejection(normalized: str) -> str:
    return f"reject:{normalized}"


def _normalized_or_none(keyword: Optional[str]) -> Optional[str]:
    if not keyword:
        return None
    norm = normalize_description(keyword)
    return norm or None


def derive_from_rejection(
    db, *, user_id: UUID | str, keyword: str,
) -> bool:
    """Write/reinforce a `reject:<normalized_keyword>` policy. Returns True
    on successful write, False on any failure (the rejection itself
    succeeded upstream — only the side effect drops)."""
    norm = _normalized_or_none(keyword)
    if not norm:
        return False
    try:
        policy_store.insert_or_reinforce(
            db,
            user_id=user_id, domain=DOMAIN, key=_key_for_rejection(norm),
            value={"rejected": True},
        )
        return True
    except Exception:
        logger.exception(
            "policy.recurring.derive_from_rejection failed for user=%s", user_id,
        )
        return False


def filter_rejected_keywords(
    db, *, user_id: UUID | str, keywords: Iterable[str],
) -> set[str]:
    """Return the SUBSET of `keywords` that are NOT rejected by a policy.

    Used by the recurring detector to drop already-rejected clusters
    before LLM tiebreaking + before the rule appears in the user's
    pending-review list. Best-effort: on lookup failure, returns all
    keywords unchanged (engine degrades to unbiased detection).
    """
    keywords = list(keywords)
    if not keywords:
        return set()

    try:
        rejected_keys = {
            o.key for o in policy_store.list_for_user(
                db, user_id=user_id, domain=DOMAIN,
            )
            if o.value.get("rejected") is True
        }
    except Exception:
        logger.exception(
            "policy.recurring.filter_rejected_keywords: lookup failed for user=%s",
            user_id,
        )
        return set(keywords)

    if not rejected_keys:
        return set(keywords)

    return {
        k for k in keywords
        if (norm := _normalized_or_none(k)) is None
        or _key_for_rejection(norm) not in rejected_keys
    }
