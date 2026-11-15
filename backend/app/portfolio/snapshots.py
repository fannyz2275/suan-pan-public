from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def get_latest_snapshot(db: Any, account_id: str) -> Optional[Dict[str, Any]]:
    """Most recent non-superseded snapshot for an account, with holdings attached."""
    snap_rows = (
        db.table("portfolio_snapshots")
        .select("*")
        .eq("account_id", account_id)
        .is_("superseded_at", None)
        .order("snapshot_date", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not snap_rows:
        return None
    snap = snap_rows[0]

    holdings = (
        db.table("snapshot_holdings")
        .select("*")
        .eq("snapshot_id", snap["id"])
        .execute()
        .data
    )
    snap["holdings"] = holdings
    return snap


def get_snapshots_in_window(
    db: Any, account_ids: List[str], from_date: date, to_date: date
) -> List[Dict[str, Any]]:
    """All non-superseded snapshots for given accounts whose snapshot_date <= to_date.

    Returns snapshots with a populated `holdings` list. We fetch from earliest
    snapshot anchoring from_date; the time-series caller decides which ones to use.
    """
    snap_rows = (
        db.table("portfolio_snapshots")
        .select("*")
        .in_("account_id", account_ids)
        .is_("superseded_at", None)
        .lte("snapshot_date", to_date.isoformat())
        .order("snapshot_date")
        .execute()
        .data
    )
    if not snap_rows:
        return []

    ids = [s["id"] for s in snap_rows]
    holdings = (
        db.table("snapshot_holdings").select("*").in_("snapshot_id", ids).execute().data
    )
    by_snap: dict[str, list] = {}
    for h in holdings:
        by_snap.setdefault(h["snapshot_id"], []).append(h)
    for s in snap_rows:
        s["holdings"] = by_snap.get(s["id"], [])
    return snap_rows


def create_manual_snapshot(
    db: Any,
    *,
    user_id: str,
    account_id: str,
    snapshot_date: date,
    cash_value: float,
    holdings: Iterable[dict],
) -> Dict[str, Any]:
    """Insert a manual snapshot + its holdings; supersede same-date manual snapshots after insert.

    Insert-first ordering ensures the prior snapshot is only orphaned if the new
    insert succeeds — avoiding a partial-failure window where supersede succeeds but
    the insert does not.
    """
    holdings_list = list(holdings)

    # Compute per-holding mv once; reuse for both snapshot total_value and holdings rows.
    holding_mvs: list[float] = []
    for h in holdings_list:
        qty = float(h["quantity"])
        price = float(h["price"])
        mv_raw = h.get("market_value")
        mv = float(mv_raw) if mv_raw is not None else qty * price
        holding_mvs.append(mv)

    total_value = float(cash_value) + sum(holding_mvs)

    # 1. Insert the new snapshot first.
    snap_row = (
        db.table("portfolio_snapshots")
        .insert({
            "user_id": user_id,
            "account_id": account_id,
            "snapshot_date": snapshot_date.isoformat(),
            "source": "manual",
            "total_value": total_value,
            "cash_value": float(cash_value),
        })
        .execute()
        .data[0]
    )

    # 2. Supersede any OTHER same-day manual snapshots (newer wins).
    (
        db.table("portfolio_snapshots")
        .update({"superseded_at": datetime.now(timezone.utc).isoformat()})
        .eq("account_id", account_id)
        .eq("snapshot_date", snapshot_date.isoformat())
        .eq("source", "manual")
        .neq("id", snap_row["id"])
        .is_("superseded_at", None)
        .execute()
    )

    # 3. Insert holdings and attach to response.
    inserted_holdings = []
    if holdings_list:
        rows = []
        for h, mv in zip(holdings_list, holding_mvs):
            qty = float(h["quantity"])
            price = float(h["price"])
            cost = h.get("cost_basis")
            unreal = (mv - float(cost)) if cost is not None else None
            rows.append({
                "snapshot_id": snap_row["id"],
                "ticker": h["ticker"],
                "quantity": qty,
                "price": price,
                "market_value": mv,
                "cost_basis": cost,
                "unrealized_gain": unreal,
            })
        inserted_holdings = (
            db.table("snapshot_holdings").insert(rows).execute().data or rows
        )

    snap_row["holdings"] = inserted_holdings
    return snap_row


def create_statement_snapshot(
    db: Any,
    *,
    user_id: str,
    account_id: str,
    snapshot_date: date,
    cash_value: float,
    holdings: Iterable[dict],
    investment_transactions: Iterable[dict],
) -> Dict[str, Any]:
    """Insert a statement-import snapshot + holdings + investment transactions.

    Same insert-first / supersede-second ordering as create_manual_snapshot. Source
    is hardcoded 'statement_import'. Investment transactions are inserted with the
    same source so they stay traceable to the import.
    """
    holdings_list = list(holdings)
    txns_list = list(investment_transactions)

    # Compute per-holding mv once; reuse for both snapshot total_value and holdings rows.
    holding_mvs: list[float] = []
    for h in holdings_list:
        qty = float(h["quantity"])
        price = float(h["price"])
        mv_raw = h.get("market_value")
        mv = float(mv_raw) if mv_raw is not None else qty * price
        holding_mvs.append(mv)

    total_value = float(cash_value) + sum(holding_mvs)

    snap_row = (
        db.table("portfolio_snapshots")
        .insert({
            "user_id": user_id,
            "account_id": account_id,
            "snapshot_date": snapshot_date.isoformat(),
            "source": "statement_import",
            "total_value": total_value,
            "cash_value": float(cash_value),
        })
        .execute()
        .data[0]
    )

    # Supersede any OTHER same-day statement_import snapshots (newer wins).
    (
        db.table("portfolio_snapshots")
        .update({"superseded_at": datetime.now(timezone.utc).isoformat()})
        .eq("account_id", account_id)
        .eq("snapshot_date", snapshot_date.isoformat())
        .eq("source", "statement_import")
        .neq("id", snap_row["id"])
        .is_("superseded_at", None)
        .execute()
    )

    inserted_holdings: list[dict] = []
    if holdings_list:
        rows = []
        for h, mv in zip(holdings_list, holding_mvs):
            qty = float(h["quantity"])
            price = float(h["price"])
            cost = h.get("cost_basis")
            unreal = (mv - float(cost)) if cost is not None else None
            rows.append({
                "snapshot_id": snap_row["id"],
                "ticker": h["ticker"],
                "quantity": qty,
                "price": price,
                "market_value": mv,
                "cost_basis": cost,
                "unrealized_gain": unreal,
            })
        inserted_holdings = (
            db.table("snapshot_holdings").insert(rows).execute().data or rows
        )

    if txns_list:
        # Idempotent re-import: delete prior statement_import txns for this account
        # within the date range we're about to write. The supersede pattern handles
        # the snapshot row; we mirror it for the txns since investment_transactions
        # has no unique constraint that catches statement-imported duplicates.
        payload_dates = [
            (d.isoformat() if hasattr(d, "isoformat") else str(d))
            for d in (t["date"] for t in txns_list)
        ]
        if payload_dates:
            min_d = min(payload_dates)
            max_d = max(payload_dates)
            (
                db.table("investment_transactions")
                .delete()
                .eq("user_id", user_id)
                .eq("account_id", account_id)
                .eq("source", "statement_import")
                .gte("date", min_d)
                .lte("date", max_d)
                .execute()
            )

        txn_rows = []
        for t in txns_list:
            d_val = t["date"]
            d_iso = d_val.isoformat() if hasattr(d_val, "isoformat") else str(d_val)
            ticker = t.get("ticker")
            qty = t.get("quantity")
            price = t.get("price")
            txn_rows.append({
                "user_id": user_id,
                "account_id": account_id,
                "date": d_iso,
                "type": t["type"],
                "ticker": ticker if ticker else None,
                "quantity": float(qty) if qty is not None else None,
                "price": float(price) if price is not None else None,
                "amount": float(t["amount"]),
                "source": "statement_import",
            })
        db.table("investment_transactions").insert(txn_rows).execute()

    snap_row["holdings"] = inserted_holdings
    return snap_row


def create_plaid_snapshot(
    db: Any,
    *,
    user_id: str,
    account_id: str,
    snapshot_date: date,
    cash_value: float,
    holdings: Iterable[dict],
    investment_transactions: Iterable[dict],
) -> Dict[str, Any]:
    """Insert a Plaid-sourced snapshot + holdings + (de-duped) investment transactions."""
    holdings_list = list(holdings)
    txns_list = list(investment_transactions)

    # Compute per-holding mv once; reuse for both snapshot total_value and snapshot_holdings.market_value.
    holding_mvs: list[float] = []
    for h in holdings_list:
        qty = float(h["quantity"])
        price = float(h["price"])
        mv_raw = h.get("market_value")
        holding_mvs.append(float(mv_raw) if mv_raw is not None else qty * price)

    total_value = float(cash_value) + sum(holding_mvs)

    snap_row = (
        db.table("portfolio_snapshots")
        .insert({
            "user_id": user_id,
            "account_id": account_id,
            "snapshot_date": snapshot_date.isoformat(),
            "source": "plaid",
            "total_value": total_value,
            "cash_value": float(cash_value),
        })
        .execute()
        .data[0]
    )

    (
        db.table("portfolio_snapshots")
        .update({"superseded_at": datetime.now(timezone.utc).isoformat()})
        .eq("account_id", account_id)
        .eq("snapshot_date", snapshot_date.isoformat())
        .eq("source", "plaid")
        .neq("id", snap_row["id"])
        .is_("superseded_at", None)
        .execute()
    )

    inserted_holdings: list[dict] = []
    if holdings_list:
        rows = []
        for h, mv in zip(holdings_list, holding_mvs):
            qty = float(h["quantity"])
            price = float(h["price"])
            cost = h.get("cost_basis")
            unreal = (mv - float(cost)) if cost is not None else None
            rows.append({
                "snapshot_id": snap_row["id"],
                "ticker": h["ticker"],
                "quantity": qty,
                "price": price,
                "market_value": mv,
                "cost_basis": cost,
                "unrealized_gain": unreal,
            })
        inserted_holdings = (
            db.table("snapshot_holdings").insert(rows).execute().data or rows
        )

    if txns_list:
        # Idempotency: skip txns whose plaid_investment_transaction_id already exists.
        plaid_ids = [
            t["plaid_investment_transaction_id"] for t in txns_list
            if t.get("plaid_investment_transaction_id")
        ]
        existing_ids: set[str] = set()
        if plaid_ids:
            existing_rows = (
                db.table("investment_transactions")
                .select("plaid_investment_transaction_id")
                .eq("user_id", user_id)
                .in_("plaid_investment_transaction_id", plaid_ids)
                .execute()
                .data
            )
            existing_ids = {r["plaid_investment_transaction_id"] for r in existing_rows}

        new_rows = []
        for t in txns_list:
            pid = t.get("plaid_investment_transaction_id")
            if pid and pid in existing_ids:
                continue
            d_val = t["date"]
            d_iso = d_val.isoformat() if hasattr(d_val, "isoformat") else str(d_val)
            ticker = t.get("ticker")
            qty = t.get("quantity")
            price = t.get("price")
            new_rows.append({
                "user_id": user_id,
                "account_id": account_id,
                "date": d_iso,
                "type": t["type"],
                "ticker": ticker if ticker else None,
                "quantity": float(qty) if qty is not None else None,
                "price": float(price) if price is not None else None,
                "amount": float(t["amount"]),
                "source": "plaid",
                "plaid_investment_transaction_id": pid,
            })

        if new_rows:
            db.table("investment_transactions").insert(new_rows).execute()

    snap_row["holdings"] = inserted_holdings
    return snap_row


def ensure_today_snapshot(
    db: Any,
    *,
    user_id: str,
    plaid_client_factory: Any,
    max_staleness_hours: int = 24,
) -> int:
    """If the user has Plaid investment accounts and the last successful Plaid
    snapshot is older than max_staleness_hours, run a sync.

    Returns the number of snapshots written this call (0 if everything is fresh
    or the user has no Plaid investment accounts).
    """
    accounts = (
        db.table("accounts").select("*")
        .eq("user_id", user_id)
        .in_("type", ["brokerage", "retirement"])
        .eq("is_active", True)
        .eq("source", "plaid")
        .execute().data
    )
    if not accounts:
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_staleness_hours)).isoformat()
    fresh = (
        db.table("portfolio_snapshots").select("id")
        .eq("user_id", user_id)
        .eq("source", "plaid")
        .gte("created_at", cutoff)
        .limit(1).execute().data
    )
    if fresh:
        return 0

    from app.portfolio.plaid_sync import sync_plaid_investments
    try:
        snaps = sync_plaid_investments(db, user_id=user_id, plaid_client=plaid_client_factory())
    except Exception:
        logger.exception("ensure_today_snapshot sync failed")
        return 0
    return len(snaps)
