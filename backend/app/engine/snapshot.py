from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID

# Per design doc: checking/savings are current (liquid) assets
LIQUID_TYPES = {"checking", "savings"}
# Brokerage are investment assets
INVESTMENT_TYPES = {"brokerage", }
NON_CURRENT_TYPES = {"property", "rsu", "business"}
RETIREMENT_TYPES = {"retirement"}
DEBT_TYPES = {"debt",}


def notional_value(account: Dict[str, Any]) -> float:
    """The account's "primary" display value.

    For checking/savings/brokerage/retirement/debt this is just the balance.
    For property / RSU / business it's a computed estimate that the UI shows
    instead of the raw balance (which is misleading for those types).
    """
    acc_type = account.get("type")
    if acc_type == "property":
        estimated = account.get("estimated_value")
        if estimated is not None:
            return float(estimated)
        return account.get("balance") or 0.0
    if acc_type == "rsu":
        vested = account.get("vested_shares") or 0.0
        unvested = account.get("unvested_shares") or 0.0
        price = account.get("grant_price") or 0.0
        return (vested + unvested) * price
    if acc_type == "business":
        valuation = account.get("estimated_valuation") or 0.0
        ownership = account.get("ownership_pct") or 0.0
        return valuation * (ownership / 100.0)
    return float(account.get("balance") or 0.0)


# Backwards-compatible private alias used by compute_snapshot (and any
# external callers that imported the old underscore-prefixed name).
_notional_value = notional_value


def compute_snapshot(accounts: List[Dict[str, Any]]) -> Dict[str, float]:
    liquid = sum(a.get("balance", 0) for a in accounts if a.get("type", "") in LIQUID_TYPES)
    investments = sum(a.get("balance", 0) for a in accounts if a.get("type", "") in INVESTMENT_TYPES | RETIREMENT_TYPES)
    non_current = sum(_notional_value(a) for a in accounts if a.get("type", "") in NON_CURRENT_TYPES)
    liabilities = sum(abs(a.get("balance", 0)) for a in accounts if a.get("type", "") in DEBT_TYPES)

    net_worth = liquid + investments + non_current - liabilities
    # Liquid net worth = current + investment assets (excludes illiquid non-current assets)
    liquid_net_worth = liquid + investments

    return {
        "liquid_assets": liquid,
        "investment_assets": investments,
        "non_current_assets": non_current,
        "total_liabilities": liabilities,
        "net_worth": net_worth,
        "liquid_net_worth": liquid_net_worth,
    }


def net_worth_at(
    db, *, user_id: str | UUID, asof: datetime,
) -> Optional[float]:
    """Reconstruct net worth as of `asof` from account_balance_history.

    For each of the user's *active* accounts, picks the latest history row
    with `as_of <= asof` and sums those balances (subtracting debt). The
    history.balance for non-current types stores the notional value
    (record_history at write-time captures re-valuations), so this matches
    `compute_snapshot`'s notional semantics over time.

    Returns None when no history rows exist at or before `asof` — the
    caller is expected to render `n/a` rather than fabricating a number.
    """
    asof_iso = asof.isoformat() if isinstance(asof, datetime) else str(asof)

    accounts = (
        db.table("accounts")
        .select("id,type")
        .eq("user_id", str(user_id))
        .eq("is_active", True)
        .execute()
        .data
        or []
    )
    if not accounts:
        return None
    type_by_id = {a["id"]: a.get("type") for a in accounts}

    rows = (
        db.table("account_balance_history")
        .select("account_id,balance,as_of")
        .eq("user_id", str(user_id))
        .lte("as_of", asof_iso)
        .order("as_of", desc=True)
        .execute()
        .data
        or []
    )
    if not rows:
        return None

    # Latest balance per account (rows are already desc-sorted, so first wins).
    latest: Dict[str, float] = {}
    for r in rows:
        aid = r["account_id"]
        if aid not in latest and aid in type_by_id:
            latest[aid] = float(r["balance"] or 0)

    if not latest:
        return None

    nw = 0.0
    for aid, bal in latest.items():
        if type_by_id[aid] in DEBT_TYPES:
            nw -= abs(bal)
        else:
            nw += bal
    return nw
