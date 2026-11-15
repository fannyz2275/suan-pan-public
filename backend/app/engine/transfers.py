"""Pure detection of inter-account transfer pairs and orphans.

The public surface is `detect_pairs_and_orphans`, which takes a list of
transaction dicts (as returned by Supabase) and returns a list of
`ScanDecision` rows — one per transaction whose status should change.
No DB access happens here; persistence is the caller's responsibility.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


PAIRING_WINDOW_DAYS = 5
FROZEN_STATUSES = {"auto_paired", "user_confirmed_internal", "external", "dismissed"}
REVIEWABLE_STATUSES: set[Optional[str]] = {None, "needs_review"}

# Case-insensitive keyword pattern. Matches common transfer descriptors.
_TRANSFER_KEYWORD_RE = re.compile(
    r"\b(transfer|xfer|ach|wire|internal transfer|zelle)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ScanDecision:
    """A single status change for one transaction."""
    txn_id: str
    new_status: str
    new_group_id: Optional[str]  # uuid string when paired, else None


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _amount(value) -> Decimal:
    # Route through str() so floats don't leak binary-precision noise into Decimal.
    return Decimal(str(value))


def _has_transfer_keyword(description: str) -> bool:
    return bool(_TRANSFER_KEYWORD_RE.search(description or ""))


def reciprocal_identity(a: dict, b: dict) -> bool:
    """Resolved reciprocal counterparties in one owner's ledger, never name similarity."""
    trusted = {'user_confirmed', 'provider_verified'}
    return bool(a.get('user_id') and a.get('user_id') == b.get('user_id')
                and a.get('account_id') and b.get('account_id')
                and a.get('counterparty_account_id') == b.get('account_id')
                and b.get('counterparty_account_id') == a.get('account_id')
                and a.get('counterparty_provenance') in trusted
                and b.get('counterparty_provenance') in trusted
                and a.get('currency') and a.get('currency') == b.get('currency'))


def detect_pairs_and_orphans(
    transactions: Iterable[dict],
) -> list[ScanDecision]:
    """Return the set of status changes to apply for the given transactions.

    Rules:
      1. Skip rows whose `transfer_status` is in FROZEN_STATUSES (user decisions are sticky).
      2. Require resolved reciprocal counterparties and matching currency/owner,
         with opposite nonzero amounts within ±PAIRING_WINDOW_DAYS days. If exactly one candidate exists
         (and is itself reviewable), emit auto_paired decisions for both with a shared
         new group id. Ambiguous (2+) matches do not pair.
      3. Any remaining reviewable row whose description matches a transfer keyword
         becomes `needs_review`.
      4. Reviewable rows with no match and no keyword are ignored (no decision).

    The caller is responsible for prefiltering by window (e.g., last 30 days) at the
    DB layer; this function only cares about pairwise relationships within the input.
    """
    candidates = [t for t in transactions if t.get("transfer_status") in REVIEWABLE_STATUSES]

    decisions: dict[str, ScanDecision] = {}
    window = timedelta(days=PAIRING_WINDOW_DAYS)

    # Phase 1: amount-match pairing.
    # Two-pass: first compute all match lists without consuming, then only pair
    # when both sides see exactly one candidate. This prevents t2 from pairing
    # with t1 when t3 also matched t1 (ambiguous from t1's perspective).
    def _find_matches(t: dict) -> list[dict]:
        target = -_amount(t["amount"])
        t_date = _parse_date(t["date"])
        return [
            c for c in candidates
            if c["id"] != t["id"]
            and c["account_id"] != t["account_id"]
            and target != 0 and target.is_finite()
            and reciprocal_identity(t, c)
            and _amount(c["amount"]) == target
            and abs(_parse_date(c["date"]) - t_date) <= window
        ]

    # Build the full match list for every candidate.
    all_matches: dict[str, list[dict]] = {
        t["id"]: _find_matches(t) for t in candidates
    }

    consumed: set[str] = set()
    for t in candidates:
        if t["id"] in consumed:
            continue
        matches = [m for m in all_matches[t["id"]] if m["id"] not in consumed]
        if len(matches) != 1:
            continue
        partner = matches[0]
        # Verify the partner also sees exactly one match (which must be t).
        partner_matches = [m for m in all_matches[partner["id"]] if m["id"] not in consumed]
        if len(partner_matches) != 1:
            continue
        group_id = str(uuid.uuid4())
        decisions[t["id"]] = ScanDecision(t["id"], "auto_paired", group_id)
        decisions[partner["id"]] = ScanDecision(partner["id"], "auto_paired", group_id)
        consumed.add(t["id"])
        consumed.add(partner["id"])

    # Phase 2: keyword-flagged orphans for the rest.
    for t in candidates:
        if t["id"] in decisions:
            continue
        if _has_transfer_keyword(t.get("description", "")):
            # Only emit a decision if the status actually changes.
            if t.get("transfer_status") != "needs_review":
                decisions[t["id"]] = ScanDecision(t["id"], "needs_review", None)

    return list(decisions.values())


@dataclass(frozen=True)
class ScanResult:
    paired_count: int
    orphan_count: int


def scan_transfers_for_user(db, user_id: str, *, window_days: int = 30) -> ScanResult:
    """Run the detector over the user's recent transactions and persist decisions.

    `db` is any object exposing the Supabase-client `.table(...)` builder — in
    production a `supabase.Client`, in tests a stub (see test_transfers_persist.py).
    """
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()

    rows = (
        db.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .gte("date", cutoff)
        .execute()
        .data
    )

    # Apply per-user transfers policy: txns matching an `external:<norm>`
    # override are filtered out before the pure detector sees them, so the
    # user doesn't have to re-mark them external on every scan.
    from app.policy import transfers as policy_transfers
    rows = policy_transfers.filter_external_candidates(
        db, user_id=user_id, candidates=rows,
    )

    decisions = detect_pairs_and_orphans(rows)
    if not decisions:
        return ScanResult(paired_count=0, orphan_count=0)

    paired = 0
    orphan = 0
    for d in decisions:
        payload = {"transfer_status": d.new_status, "transfer_group_id": d.new_group_id}
        db.table("transactions").update(payload).eq("id", d.txn_id).execute()
        if d.new_status == "auto_paired":
            paired += 1
        elif d.new_status == "needs_review":
            orphan += 1

    # Paired rows are emitted as pairs; divide by 2 for the count of pair-events.
    return ScanResult(paired_count=paired // 2, orphan_count=orphan)


def safe_scan_transfers_for_user(db, user_id: str) -> None:
    """Run scan_transfers_for_user and swallow exceptions.

    A scan glitch must never fail the upstream transaction-write path; we just
    log and move on so the user's data still lands.
    """
    try:
        scan_transfers_for_user(db, user_id=user_id)
    except Exception:
        logger.exception("transfer scan failed for user %s", user_id)
