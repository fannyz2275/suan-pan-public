"""
Seed — deterministic test-DB fixture builder for all three eval specs.

Design goals:
  * Idempotent: apply() uses upsert so calling it twice leaves the DB in
    the same state.
  * Predictable ids: account_id defaults to a slug of the account name so
    the same fixture always produces the same ids across runs.
  * Stand-alone: no imports from app.* modules (keeps the three specs
    free of circular dependencies on each other).
  * Compatible with real Supabase clients AND MagicMock stubs — the only
    interface used is .table(name).upsert/insert(payload).execute().

Column names are taken verbatim from:
  * backend/supabase/schema.sql          — accounts, goals, profiles
  * backend/supabase/migrations/2026-05-06-portfolio-snapshots.sql
    — portfolio_snapshots, snapshot_holdings, investment_transactions,
      security_reference
"""

from __future__ import annotations

import re
import uuid
from collections import namedtuple
from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# AppliedSeed — returned by .apply(); carries the stable ids that landed in DB
# ---------------------------------------------------------------------------

AppliedSeed = namedtuple(
    "AppliedSeed",
    ["user_id", "account_ids", "snapshot_ids", "goal_ids"],
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    """Convert a free-form name into a URL-safe slug for stable id generation."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _to_date_str(d: date | str) -> str:
    """Normalise a date or ISO string to 'YYYY-MM-DD'."""
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def _stable_uuid(seed_str: str) -> str:
    """Generate a deterministic UUID string from a seed string (UUID v5, DNS namespace)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, seed_str))


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

class Seed:
    """Deterministic test-DB fixture builder. Idempotent: calling apply()
    twice produces the same end state. Used by all three eval specs."""

    def __init__(self) -> None:
        self._user_id: str = "u-test"
        self._accounts: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []          # each has '_holdings' sub-list
        self._investment_txns: list[dict[str, Any]] = []
        self._securities: list[dict[str, Any]] = []
        self._goals: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Builder methods — all return self for chaining
    # ------------------------------------------------------------------

    def with_user(self, user_id: str = "u-test") -> "Seed":
        self._user_id = user_id
        return self

    def with_account(
        self,
        *,
        account_id: str | None = None,
        name: str = "Test Brokerage",
        type: str = "brokerage",
        balance: float = 0,
        source: str = "manual",
        plaid_account_id: str | None = None,
    ) -> "Seed":
        resolved_id = account_id or f"acc-{_slug(name)}"
        self._accounts.append({
            "account_id": resolved_id,
            "name": name,
            "type": type,
            "balance": balance,
            "source": source,
            "plaid_account_id": plaid_account_id,
        })
        return self

    def with_snapshot(
        self,
        *,
        account_id: str,
        snapshot_date: date | str,
        cash_value: float = 0,
        source: str = "manual",
        holdings: list[dict] | None = None,
        total_value: float | None = None,
    ) -> "Seed":
        if holdings is None:
            holdings = []

        # Resolve market_value for each holding (qty × price if absent)
        resolved_holdings = []
        for h in holdings:
            h = dict(h)  # copy so we don't mutate caller's dict
            qty = float(h.get("quantity", h.get("qty", 0)))
            price = float(h.get("price", 0))
            if "market_value" not in h:
                h["market_value"] = round(qty * price, 2)
            # Normalise 'qty' -> 'quantity' for DB consistency
            if "qty" in h and "quantity" not in h:
                h["quantity"] = h.pop("qty")
            resolved_holdings.append(h)

        # Auto-compute total_value if not supplied
        if total_value is None:
            holdings_value = sum(float(h["market_value"]) for h in resolved_holdings)
            total_value = round(cash_value + holdings_value, 2)

        # Stable snapshot_id from (account_id, date, source)
        snap_key = f"snap-{account_id}-{_to_date_str(snapshot_date)}-{source}"
        snapshot_id = _stable_uuid(snap_key)

        self._snapshots.append({
            "snapshot_id": snapshot_id,
            "account_id": account_id,
            "snapshot_date": _to_date_str(snapshot_date),
            "source": source,
            "total_value": total_value,
            "cash_value": cash_value,
            "_holdings": resolved_holdings,
        })
        return self

    def with_investment_txn(
        self,
        *,
        account_id: str,
        date: date | str,
        type: str,
        ticker: str | None = None,
        quantity: float | None = None,
        price: float | None = None,
        amount: float,
        source: str = "manual",
    ) -> "Seed":
        self._investment_txns.append({
            "account_id": account_id,
            "date": _to_date_str(date),
            "type": type,
            "ticker": ticker,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "source": source,
        })
        return self

    def with_security(
        self,
        *,
        ticker: str,
        asset_class: str = "equity",
        sector: str | None = None,
        region: str = "US",
        look_through: list[dict] | None = None,
        security_type: str = "stock",
    ) -> "Seed":
        self._securities.append({
            "ticker": ticker,
            "asset_class": asset_class,
            "sector": sector,
            "region": region,
            "look_through": look_through,
            "security_type": security_type,
        })
        return self

    def with_goal(
        self,
        *,
        name: str,
        type: str,
        target_amount: float,
        target_date: date | str,
        **kwargs,
    ) -> "Seed":
        goal = {
            "name": name,
            "type": type,
            "target_amount": target_amount,
            "target_date": _to_date_str(target_date),
            **kwargs,
        }
        self._goals.append(goal)
        return self

    # ------------------------------------------------------------------
    # apply() — write everything to the DB and return AppliedSeed
    # ------------------------------------------------------------------

    def apply(self, db) -> AppliedSeed:
        """Insert all queued state into the DB. Returns AppliedSeed with stable ids.

        Uses upsert (on_conflict=ignore) throughout so repeated calls
        produce the same end state.
        """
        user_id = self._user_id

        # 1. Upsert profile row (only id needed; other fields are optional)
        db.table("profiles").upsert(
            {"id": user_id},
            on_conflict="id",
        ).execute()

        # 2. Upsert accounts
        account_ids: dict[str, str] = {}   # name → resolved account_id
        for acc in self._accounts:
            resolved_id = acc["account_id"]
            account_ids[acc["name"]] = resolved_id
            db.table("accounts").upsert(
                {
                    "id": resolved_id,
                    "user_id": user_id,
                    "name": acc["name"],
                    "type": acc["type"],
                    "balance": acc["balance"],
                    "source": acc["source"],
                    **({"plaid_account_id": acc["plaid_account_id"]}
                       if acc["plaid_account_id"] else {}),
                },
                on_conflict="id",
            ).execute()

        # 3. Upsert securities (shared reference table, no user_id)
        for sec in self._securities:
            db.table("security_reference").upsert(
                {
                    "ticker": sec["ticker"],
                    "asset_class": sec["asset_class"],
                    "sector": sec["sector"],
                    "region": sec["region"],
                    "look_through": sec["look_through"],
                    "security_type": sec["security_type"],
                },
                on_conflict="ticker",
            ).execute()

        # 4. Upsert portfolio_snapshots + insert snapshot_holdings
        snapshot_ids: list[str] = []
        for snap in self._snapshots:
            snap_id = snap["snapshot_id"]
            snapshot_ids.append(snap_id)

            db.table("portfolio_snapshots").upsert(
                {
                    "id": snap_id,
                    "user_id": user_id,
                    "account_id": snap["account_id"],
                    "snapshot_date": snap["snapshot_date"],
                    "source": snap["source"],
                    "total_value": snap["total_value"],
                    "cash_value": snap["cash_value"],
                },
                on_conflict="id",
            ).execute()

            # Holdings: insert as a batch (portfolio_snapshots cascade deletes
            # these, so we rely on the snapshot upsert being idempotent first)
            holding_rows = []
            for h in snap["_holdings"]:
                qty = float(h.get("quantity", h.get("qty", 0)))
                price = float(h.get("price", 0))
                row = {
                    "snapshot_id": snap_id,
                    "ticker": h["ticker"],
                    "quantity": qty,
                    "price": price,
                    "market_value": float(h["market_value"]),
                }
                if h.get("cost_basis") is not None:
                    row["cost_basis"] = float(h["cost_basis"])
                holding_rows.append(row)

            if holding_rows:
                db.table("snapshot_holdings").insert(holding_rows).execute()

        # 5. Insert investment_transactions
        for txn in self._investment_txns:
            db.table("investment_transactions").upsert(
                {
                    "user_id": user_id,
                    "account_id": txn["account_id"],
                    "date": txn["date"],
                    "type": txn["type"],
                    "ticker": txn.get("ticker"),
                    "quantity": txn.get("quantity"),
                    "price": txn.get("price"),
                    "amount": txn["amount"],
                    "source": txn["source"],
                },
                on_conflict="id",
            ).execute()

        # 6. Upsert goals
        goal_ids: list[str] = []
        for goal in self._goals:
            # Stable goal id from (user_id, name)
            goal_id = _stable_uuid(f"goal-{user_id}-{goal['name']}")
            goal_ids.append(goal_id)
            db.table("goals").upsert(
                {
                    "id": goal_id,
                    "user_id": user_id,
                    "name": goal["name"],
                    "type": goal["type"],
                    "target_amount": goal["target_amount"],
                    "target_date": goal["target_date"],
                    **{k: v for k, v in goal.items()
                       if k not in ("name", "type", "target_amount", "target_date")},
                },
                on_conflict="id",
            ).execute()

        return AppliedSeed(
            user_id=user_id,
            account_ids=account_ids,
            snapshot_ids=snapshot_ids,
            goal_ids=goal_ids,
        )
