"""Tier 2 KPIs — pure DB queries + Python math, no LLM round-trips.

Four metrics rendered into the LIVE STATE block of every advisor turn:

  • liquidity_ratio        — latest cash equivalents / monthly burn
  • savings_rate           — median monthly (income − expenses) / median income
  • nw_yoy_growth          — (NW_now − NW_then) / NW_then × 365/N, N≥90d
  • yield_on_net_worth     — median monthly investment growth / median monthly expenses

Each function returns `None` when its data prerequisite is not met. The
prompt renderer maps `None` → `n/a` so the LLM is told what's missing
rather than getting a fabricated number. This is the "n/a is honest"
invariant — see README.md, "Carry your priorities into the next conversation".

The two design decisions baked in:

1. Medians, not means. Robust to bonus / RSU / one-off-spike months.
2. Rolling 6-month window with all-history fallback. Trades a small bias
   against very recent users (whose 6mo window is light) for a strong
   noise floor on long-tenured users.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Iterable, Optional
from uuid import UUID


LIQUID_ACCOUNT_TYPES = ("checking", "savings")
INVESTMENT_ACCOUNT_TYPES = ("brokerage", "retirement")
LOOKBACK_MONTHS = 6
NW_GROWTH_MIN_DAYS = 90


# ---- shared helpers --------------------------------------------------------


def _today() -> date:
    return date.today()


def _ymd(d: date) -> str:
    return d.isoformat()


def _bucket_by_month(rows: Iterable[dict], date_field: str, amount_field: str) -> dict[str, float]:
    """Sum signed amounts into yyyy-mm buckets. Skips rows missing the date."""
    out: dict[str, float] = {}
    for r in rows:
        d = r.get(date_field)
        if not d:
            continue
        ym = str(d)[:7]
        out[ym] = out.get(ym, 0.0) + float(r.get(amount_field) or 0)
    return out


def monthly_income_expense_medians(
    db, *, user_id: str | UUID, today: Optional[date] = None,
) -> Optional[tuple[float, float]]:
    """Returns (income_median, expense_median) over the rolling window, or None
    when there are no transactions in window.

    Excludes `category='transfer'` rows — internal moves between accounts must
    not count as income or expense. Income = positive amount; expense = abs of
    negative amount.
    """
    today = today or _today()
    cutoff = today - timedelta(days=30 * LOOKBACK_MONTHS)
    rows = (
        db.table("transactions")
        .select("date,amount,category")
        .eq("user_id", str(user_id))
        .gte("date", _ymd(cutoff))
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    rows = [r for r in rows if (r.get("category") or "") != "transfer"]
    income_rows = [r for r in rows if float(r.get("amount") or 0) > 0]
    expense_rows = [
        {"date": r["date"], "amount": abs(float(r["amount"]))}
        for r in rows
        if float(r.get("amount") or 0) < 0
    ]
    inc_by_month = _bucket_by_month(income_rows, "date", "amount")
    exp_by_month = _bucket_by_month(expense_rows, "date", "amount")
    if not inc_by_month and not exp_by_month:
        return None
    inc_med = median(inc_by_month.values()) if inc_by_month else 0.0
    exp_med = median(exp_by_month.values()) if exp_by_month else 0.0
    return inc_med, exp_med


# ---- KPI 1: liquidity_ratio -----------------------------------------------


def liquidity_ratio(
    db, *, user_id: str | UUID, recurring_rules,
) -> Optional[float]:
    """latest cash equivalents (checking + savings) divided by recurring
    monthly outflow.

    Returns None when there is no recurring outflow yet — variable-spend-only
    users can't have a meaningful "runway in months." The prompt renders n/a.
    """
    # Avoid the import cycle by deferring; compute_recurring_totals lives in
    # advisor.context but is a pure helper over RecurringRule objects.
    from app.advisor.context import compute_recurring_totals

    totals = compute_recurring_totals(recurring_rules or [])
    burn = totals["fixed_monthly_outflow"]
    if not burn or burn <= 0:
        return None

    accounts = (
        db.table("accounts")
        .select("balance,type")
        .eq("user_id", str(user_id))
        .eq("is_active", True)
        .in_("type", list(LIQUID_ACCOUNT_TYPES))
        .execute()
        .data
        or []
    )
    cash_total = sum(float(a.get("balance") or 0) for a in accounts)
    return cash_total / burn


# ---- KPI 2: savings_rate ---------------------------------------------------


def savings_rate(
    db, *, user_id: str | UUID, today: Optional[date] = None,
) -> Optional[float]:
    """(median monthly income − median monthly expenses) / median monthly income.

    Returns None when the user has no income transactions in window — the rate
    is undefined without a denominator.
    """
    medians = monthly_income_expense_medians(db, user_id=user_id, today=today)
    if medians is None:
        return None
    inc_med, exp_med = medians
    if inc_med <= 0:
        return None
    return (inc_med - exp_med) / inc_med


# ---- KPI 3: nw_yoy_growth --------------------------------------------------


def nw_yoy_growth(
    db, *, user_id: str | UUID, today: Optional[date] = None,
) -> Optional[float]:
    """Annualized net-worth growth, computed over whatever window of history
    is available — provided that window is at least 90 days.

    Formula: (NW_now − NW_t) / NW_t × 365 / N where N is the number of days
    between the user's earliest balance-history row and today.

    Returns None when:
      • no balance history exists,
      • the earliest history row is < 90 days old,
      • or the historical NW reconstruction returns None / 0.
    """
    today = today or _today()

    earliest = (
        db.table("account_balance_history")
        .select("as_of")
        .eq("user_id", str(user_id))
        .order("as_of")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not earliest:
        return None

    earliest_iso = earliest[0]["as_of"]
    try:
        earliest_dt = datetime.fromisoformat(earliest_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

    n_days = (today - earliest_dt.date()).days
    if n_days < NW_GROWTH_MIN_DAYS:
        return None

    # Import here to avoid the engine.snapshot ↔ engine.kpis cycle staying flat.
    from app.engine.snapshot import compute_snapshot, net_worth_at

    accounts = (
        db.table("accounts")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("is_active", True)
        .execute()
        .data
        or []
    )
    nw_now = compute_snapshot(accounts)["net_worth"]
    nw_then = net_worth_at(db, user_id=user_id, asof=earliest_dt)
    if not nw_then:
        return None

    return (nw_now - nw_then) / nw_then * 365 / n_days


# ---- KPI 4: yield_on_net_worth --------------------------------------------


def yield_on_net_worth(
    db, *, user_id: str | UUID, today: Optional[date] = None,
) -> Optional[float]:
    """Median monthly investment growth divided by median monthly expenses.

    Reads as: "passive income coverage of cost-of-living." A value of 1.0
    means investments are throwing off enough on average to cover monthly
    expenses; 0.4 means 40% covered.

    Returns None when:
      • the user has no investment-typed accounts,
      • investment history yields fewer than 2 distinct months in window,
      • or there are no expenses to divide by.
    """
    today = today or _today()
    cutoff = today - timedelta(days=30 * LOOKBACK_MONTHS)

    inv_accounts = (
        db.table("accounts")
        .select("id,type")
        .eq("user_id", str(user_id))
        .eq("is_active", True)
        .in_("type", list(INVESTMENT_ACCOUNT_TYPES))
        .execute()
        .data
        or []
    )
    if not inv_accounts:
        return None
    inv_ids = {a["id"] for a in inv_accounts}

    history = (
        db.table("account_balance_history")
        .select("account_id,balance,as_of")
        .eq("user_id", str(user_id))
        .gte("as_of", cutoff.isoformat())
        .order("as_of")
        .execute()
        .data
        or []
    )
    inv_history = [r for r in history if r["account_id"] in inv_ids]

    # Roll up to (account_id, yyyy-mm) → last balance of the month.
    by_acct_month: dict[tuple[str, str], float] = {}
    for r in inv_history:
        ym = str(r["as_of"])[:7]
        by_acct_month[(r["account_id"], ym)] = float(r["balance"] or 0)

    # Total invested per month = sum across accounts of last-known balance
    # *available at that month or earlier* — a missing month for an account
    # carries its previous balance forward (otherwise a sparse history
    # account drops out and skews the total).
    months = sorted({ym for (_, ym) in by_acct_month})
    if len(months) < 2:
        return None
    last_known: dict[str, float] = {}
    monthly_total: dict[str, float] = {}
    for ym in months:
        for aid in inv_ids:
            if (aid, ym) in by_acct_month:
                last_known[aid] = by_acct_month[(aid, ym)]
        monthly_total[ym] = sum(last_known.values())

    growths = [
        monthly_total[months[i]] - monthly_total[months[i - 1]]
        for i in range(1, len(months))
    ]
    if not growths:
        return None
    grow_med = median(growths)

    medians = monthly_income_expense_medians(db, user_id=user_id, today=today)
    if medians is None:
        return None
    _, exp_med = medians
    if exp_med <= 0:
        return None

    return grow_med / exp_med


__all__ = [
    "liquidity_ratio",
    "savings_rate",
    "nw_yoy_growth",
    "yield_on_net_worth",
    "monthly_income_expense_medians",
    "LOOKBACK_MONTHS",
    "NW_GROWTH_MIN_DAYS",
]
