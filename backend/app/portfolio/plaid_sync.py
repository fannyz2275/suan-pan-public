from __future__ import annotations

import logging
from datetime import date as _date, timedelta as _td
from typing import Any, Dict, Iterable, List, Optional

import plaid
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest

from app.portfolio import snapshots as snapshots_module

logger = logging.getLogger(__name__)

_INVESTMENT_TXNS_LOOKBACK_DAYS = 90

# Plaid security.type → our security_reference.security_type
_PLAID_TYPE_TO_TYPE = {
    "equity": "stock",
    "etf": "etf",
    "mutual fund": "mutual_fund",
    "fixed income": "bond",
    "cash": "cash",
    "derivative": "other",
    "loan": "other",
    "other": "other",
}

# Plaid security.type → our security_reference.asset_class
_PLAID_TYPE_TO_ASSET_CLASS = {
    "equity": "equity",
    "etf": "equity",
    "mutual fund": "equity",
    "fixed income": "fixed_income",
    "cash": "cash",
    "derivative": "other",
    "loan": "other",
    "other": "other",
}

# Plaid investment-transaction (type, subtype) → our investment_transactions.type
# Reference: https://plaid.com/docs/api/products/investments/#investments-transactions-get
def _normalize_plaid_txn(plaid_type: str, subtype: Optional[str]) -> Optional[str]:
    t = (plaid_type or "").lower().strip()
    s = (subtype or "").lower().strip() if subtype else ""

    if t == "buy":
        return "buy"
    if t == "sell":
        return "sell"
    if t == "cash":
        if s == "dividend":
            return "dividend"
        if s == "interest":
            return "interest"
        return None
    if t == "fee":
        return "fee"
    if t == "transfer":
        if s in {"deposit", "contribution", "transfer_in"}:
            return "transfer_in"
        if s in {"withdrawal", "distribution", "transfer_out"}:
            return "transfer_out"
        return None
    if t == "stock_split" or s in {"split", "stock_split"}:
        return "split"
    return None


def _security_index(securities: Iterable[dict]) -> Dict[str, dict]:
    return {s["security_id"]: s for s in securities if s.get("security_id")}


def map_plaid_holdings(
    holdings: Iterable[dict], securities: Iterable[dict]
) -> Dict[str, Dict[str, Any]]:
    """Group Plaid holdings by Plaid account_id; cash-equivalents go to cash_value.

    Returns: { plaid_account_id: { "cash_value": float, "holdings": [holding_dict, ...] } }
    """
    sec_by_id = _security_index(securities)
    out: Dict[str, Dict[str, Any]] = {}

    for h in holdings:
        acct = h.get("account_id")
        sec_id = h.get("security_id")
        if not acct or not sec_id:
            continue
        sec = sec_by_id.get(sec_id)
        if not sec:
            continue

        bucket = out.setdefault(acct, {"cash_value": 0.0, "holdings": []})

        if sec.get("is_cash_equivalent") or sec.get("type") == "cash":
            mv = float(h.get("institution_value") or 0)
            bucket["cash_value"] += mv
            continue

        ticker = (sec.get("ticker_symbol") or "").upper().strip()
        if not ticker:
            continue
        qty = float(h.get("quantity") or 0)
        price = float(h.get("institution_price") or 0)
        mv_raw = h.get("institution_value")
        mv = float(mv_raw) if mv_raw is not None else qty * price
        cost_basis_raw = h.get("cost_basis")
        cost_basis = float(cost_basis_raw) if cost_basis_raw is not None else None

        bucket["holdings"].append({
            "ticker": ticker,
            "name": sec.get("name"),
            "quantity": qty,
            "price": price,
            "market_value": mv,
            "cost_basis": cost_basis,
        })

    return out


def map_plaid_investment_transactions(
    plaid_txns: Iterable[dict], securities: Iterable[dict]
) -> Dict[str, List[Dict[str, Any]]]:
    """Group Plaid investment-transactions by Plaid account_id.

    Sign convention: Plaid uses positive amount for cash-out (buy, fee, withdrawal).
    Our schema uses signed cash impact (positive = cash arriving in account).
    Buy / fee / transfer_out get sign-flipped; sell / dividend / transfer_in keep sign.
    """
    sec_by_id = _security_index(securities)
    out: Dict[str, List[Dict[str, Any]]] = {}

    for t in plaid_txns:
        acct = t.get("account_id")
        if not acct:
            continue
        kind = _normalize_plaid_txn(t.get("type"), t.get("subtype"))
        if kind is None:
            continue
        amount = float(t.get("amount") or 0)
        if kind in {"buy", "fee", "transfer_out"} and amount > 0:
            amount = -amount  # flip Plaid's positive-cash-out convention

        ticker: Optional[str] = None
        sec = sec_by_id.get(t.get("security_id") or "")
        if sec:
            ts = sec.get("ticker_symbol")
            if ts:
                ticker = ts.upper().strip()

        date_val = t.get("date")
        date_iso = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)

        qty_raw = t.get("quantity")
        price_raw = t.get("price")
        try:
            qty = float(qty_raw) if qty_raw not in (None, 0) else None
        except (TypeError, ValueError):
            qty = None
        try:
            price = float(price_raw) if price_raw not in (None, 0) else None
        except (TypeError, ValueError):
            price = None

        out.setdefault(acct, []).append({
            "date": date_iso,
            "type": kind,
            "ticker": ticker,
            "quantity": qty,
            "price": price,
            "amount": amount,
            "plaid_investment_transaction_id": t.get("investment_transaction_id"),
        })

    return out


def securities_to_reference_rows(securities: Iterable[dict]) -> List[Dict[str, Any]]:
    """Build security_reference upsert rows from a Plaid securities array.

    Skips cash equivalents and entries without a ticker. Sector / region / look_through
    are left null — Plan 1's yfinance enrichment populates those separately.
    """
    out: List[Dict[str, Any]] = []
    for s in securities:
        if s.get("is_cash_equivalent"):
            continue
        ticker = (s.get("ticker_symbol") or "").upper().strip()
        if not ticker:
            continue
        ptype = (s.get("type") or "").lower().strip()
        out.append({
            "ticker": ticker,
            "name": s.get("name"),
            "security_type": _PLAID_TYPE_TO_TYPE.get(ptype, "other"),
            "asset_class": _PLAID_TYPE_TO_ASSET_CLASS.get(ptype, "other"),
            "sector": None,
            "region": None,
            "look_through": None,
            "enrichment_source": "plaid",
        })
    return out


def sync_plaid_investments(db: Any, *, user_id: str, plaid_client: Any) -> List[Dict[str, Any]]:
    """For each Plaid item the user owns, fetch holdings + investment txns and
    write a snapshot per investment account. Returns the list of snapshots written.

    Failures on any single item are logged and skipped; other items still sync.
    """
    items = (
        db.table("plaid_items").select("*").eq("user_id", user_id).execute().data
    )
    if not items:
        return []

    accounts = (
        db.table("accounts").select("*")
        .eq("user_id", user_id)
        .in_("type", ["brokerage", "retirement"])
        .eq("is_active", True)
        .execute().data
    )
    account_by_plaid_id = {
        a["plaid_account_id"]: a for a in accounts if a.get("plaid_account_id")
    }
    if not account_by_plaid_id:
        return []

    today = _date.today()
    start_date = today - _td(days=_INVESTMENT_TXNS_LOOKBACK_DAYS)
    snapshots_written: list[dict] = []

    for item in items:
        access_token = item["access_token"]

        try:
            holdings_resp = plaid_client.investments_holdings_get(
                InvestmentsHoldingsGetRequest(access_token=access_token)
            )
        except plaid.ApiException:
            logger.exception(
                "Plaid investments/holdings/get failed for item %s", item.get("item_id")
            )
            continue

        try:
            txns_resp = plaid_client.investments_transactions_get(
                InvestmentsTransactionsGetRequest(
                    access_token=access_token,
                    start_date=start_date,
                    end_date=today,
                )
            )
        except plaid.ApiException:
            logger.exception(
                "Plaid investments/transactions/get failed for item %s", item.get("item_id")
            )
            txns_resp = {"investment_transactions": [], "securities": []}

        # Upsert security_reference rows for any Plaid-known securities we haven't seen.
        all_securities = list(holdings_resp.get("securities", [])) + list(
            txns_resp.get("securities", [])
        )
        ref_rows = securities_to_reference_rows(all_securities)
        if ref_rows:
            try:
                db.table("security_reference").upsert(ref_rows, on_conflict="ticker").execute()
            except Exception:
                logger.exception("security_reference upsert failed")

        holdings_by_account = map_plaid_holdings(
            holdings_resp.get("holdings", []), all_securities
        )
        txns_by_account = map_plaid_investment_transactions(
            txns_resp.get("investment_transactions", []), all_securities
        )

        # Plaid's account.balances.current acts as a tie-out reference.
        plaid_balance_by_acct: dict[str, float] = {}
        for a in holdings_resp.get("accounts", []):
            cur = (a.get("balances") or {}).get("current")
            if cur is not None:
                plaid_balance_by_acct[a["account_id"]] = float(cur)

        for plaid_acc_id, payload in holdings_by_account.items():
            our = account_by_plaid_id.get(plaid_acc_id)
            if not our:
                continue  # Plaid account that isn't an investment account in our DB.

            computed_total = float(payload["cash_value"]) + sum(
                float(h.get("market_value") if h.get("market_value") is not None else h["quantity"] * h["price"])
                for h in payload["holdings"]
            )
            plaid_total = plaid_balance_by_acct.get(plaid_acc_id)
            if plaid_total is not None:
                tolerance = max(abs(plaid_total) * 0.01, 1.0)
                if abs(computed_total - plaid_total) > tolerance:
                    logger.warning(
                        "Plaid tie-out mismatch on account %s: computed %.2f vs Plaid balance %.2f",
                        our["id"],
                        computed_total,
                        plaid_total,
                    )

            snap = snapshots_module.create_plaid_snapshot(
                db,
                user_id=user_id,
                account_id=our["id"],
                snapshot_date=today,
                cash_value=payload["cash_value"],
                holdings=payload["holdings"],
                investment_transactions=txns_by_account.get(plaid_acc_id, []),
            )
            snapshots_written.append(snap)

    return snapshots_written
