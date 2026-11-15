"""Helpers for recording account-balance changes.

Two concerns:

1. The denormalized cache on the `accounts` row (balance_updated_at /
   previous_balance / previous_balance_at) — useful for the UI to warn the
   user that a recent upload overwrote their hand-entered number. Owned by
   `cache_patch` (formerly balance_history_patch — kept as alias for the
   transitional window).

2. The full history in `account_balance_history` (one row per balance
   change) — the source of truth for the NW yoy KPI in T2. Owned by
   `record_history`. PR-A wires this into all four write paths (manual
   create + edit, file import, Plaid sync).

Callers should treat these as a pair: every balance write should both
update the cache fields AND insert a history row, so the prompt renders
honest numbers and the UI keeps its hand-entered-vs-uploaded affordance.
"""

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

BalanceSource = Literal["initial", "manual", "plaid", "file_import"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cache_patch(existing: dict | None, new_balance: float | None) -> dict:
    """Return the partial-update dict that should be merged into an `accounts`
    write to keep the cache fields (balance_updated_at, previous_balance,
    previous_balance_at) consistent.

    `existing` is the current row (must include `balance`, `balance_updated_at`,
    `created_at`) or None on insert. `new_balance` is what the caller is about
    to write.
    """
    if new_balance is None:
        return {}

    now_iso = _utc_now_iso()

    if existing is None:
        return {"balance_updated_at": now_iso}

    cur_balance = existing.get("balance")
    if cur_balance is None or float(cur_balance) == float(new_balance):
        return {"balance_updated_at": now_iso}

    return {
        "balance_updated_at": now_iso,
        "previous_balance": cur_balance,
        "previous_balance_at": (
            existing.get("balance_updated_at") or existing.get("created_at")
        ),
    }


# Backward-compat alias — call sites migrate to `cache_patch` over time.
balance_history_patch = cache_patch


def record_history(
    db,
    *,
    account_id: str | UUID,
    user_id: str | UUID,
    balance: float | None,
    source: BalanceSource,
    as_of: Optional[datetime] = None,
) -> None:
    """Insert a row into account_balance_history. No-op on None balance.

    `as_of` defaults to now(); pass an explicit timestamp when the source
    has one (e.g. Plaid `last_updated`, or a parsed statement date). The
    insert is best-effort — failures are logged but do not break the
    account write that triggered them.
    """
    if balance is None:
        return
    when = (as_of or datetime.now(timezone.utc)).isoformat()
    try:
        db.table("account_balance_history").insert({
            "account_id": str(account_id),
            "user_id": str(user_id),
            "balance": float(balance),
            "as_of": when,
            "source": source,
        }).execute()
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "record_history failed: account=%s source=%s", account_id, source,
        )
