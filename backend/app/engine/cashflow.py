from datetime import date
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Any, Optional

from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Status,
)


FREQ_PER_YEAR: dict[Frequency, int] = {
    Frequency.WEEKLY: 52,
    Frequency.BIWEEKLY: 26,
    Frequency.SEMI_MONTHLY: 24,
    Frequency.MONTHLY: 12,
    Frequency.QUARTERLY: 4,
    Frequency.SEMI_ANNUAL: 2,
    Frequency.ANNUAL: 1,
}

_ACTIVE_RULE_STATUSES = {Status.USER_CONFIRMED, Status.AUTO_APPLIED}


def _monthly_equivalent(rule: RecurringRule, month_index: int) -> float:
    per_year = FREQ_PER_YEAR[rule.frequency]
    if per_year >= 12:
        return rule.amount_median * (per_year / 12)
    cycle = 12 // per_year
    if (month_index + 1) % cycle == 0:
        return rule.amount_median
    return 0.0


def project_cashflow(
    liquid_assets: float,
    monthly_income: float,
    monthly_expenses: float,
    months: int = 12,
    vesting_events: Optional[List[Dict[str, Any]]] = None,
    start_date: Optional[date] = None,
    recurring_rules: Optional[List[RecurringRule]] = None,
    baselined_months: Optional[List[tuple]] = None,
) -> List[Dict[str, Any]]:
    """
    Projects month-by-month cash balance.
    vesting_events: list of {"date": "YYYY-MM-DD", "value": float}
    recurring_rules: active rules consumed into fixed_inflow / fixed_outflow per month.
    baselined_months: optional list of (month_str, expected, low, high) tuples
        from category_baseline.project_baselined_months. When provided, these
        amounts are applied as additional outflow per month and surface as
        projected_expense_low/high in the response.
    """
    if start_date is None:
        start_date = date.today()
    rules = [r for r in (recurring_rules or []) if r.status in _ACTIVE_RULE_STATUSES]

    vest_by_month: Dict[str, float] = {}
    for event in (vesting_events or []):
        d = date.fromisoformat(event["date"])
        key = d.strftime("%Y-%m")
        vest_by_month[key] = vest_by_month.get(key, 0) + event["value"]

    baselined_by_month: Dict[str, tuple] = {
        m[0]: m for m in (baselined_months or [])
    }

    monthly_net = monthly_income - monthly_expenses
    balance = liquid_assets
    result = []

    for i in range(months):
        month_date = start_date + relativedelta(months=i + 1)
        month_key = month_date.strftime("%Y-%m")
        fixed_inflow = 0.0
        fixed_outflow = 0.0
        for r in rules:
            contribution = _monthly_equivalent(r, i)
            if r.direction == Direction.INCOME:
                fixed_inflow += contribution
            else:
                fixed_outflow += contribution
        vest = vest_by_month.get(month_key, 0.0)

        baselined_expected = 0.0
        baselined_low = 0.0
        baselined_high = 0.0
        if month_key in baselined_by_month:
            _, baselined_expected, baselined_low, baselined_high = baselined_by_month[month_key]

        balance = (
            balance + monthly_net + fixed_inflow - fixed_outflow + vest
            - baselined_expected
        )

        row = {
            "month": month_key,
            "balance": round(balance, 2),
            "monthly_net": round(monthly_net, 2),
            "fixed_inflow": round(fixed_inflow, 2),
            "fixed_outflow": round(fixed_outflow, 2),
            "vesting_income": vest,
        }
        if month_key in baselined_by_month:
            row["projected_expense_expected"] = round(baselined_expected, 2)
            row["projected_expense_low"] = round(baselined_low, 2)
            row["projected_expense_high"] = round(baselined_high, 2)
        result.append(row)

    return result


def compute_historical_cashflow(
    transactions: List[Dict[str, Any]],
    ending_balance: float,
    months: int = 12,
) -> List[Dict[str, Any]]:
    """Past N months of actual cash flow, walked backward from `ending_balance`.

    `transactions` items must have `date` (YYYY-MM-DD) and signed `amount`
    (positive = inflow, negative = outflow). The current month and any
    future-dated transactions are excluded — the series ends with the month
    immediately before today's month, and `ending_balance` is taken as the
    end-of-month balance for that final month.

    Returns oldest-first, length == months, each entry: {month, balance, net}.
    """
    today = date.today()
    # Use replace() so we never call the date constructor directly — keeps
    # unittest.mock.patch("app.engine.cashflow.date") working cleanly.
    current_month_start = today.replace(day=1)
    month_keys: List[str] = []
    for i in range(months, 0, -1):
        d = current_month_start - relativedelta(months=i)
        month_keys.append(d.strftime("%Y-%m"))

    current_month_key = current_month_start.strftime("%Y-%m")

    net_by_month: Dict[str, float] = {k: 0.0 for k in month_keys}
    for txn in transactions or []:
        d = date.fromisoformat(txn["date"])
        txn_key = d.strftime("%Y-%m")
        if txn_key >= current_month_key:
            continue
        if txn_key in net_by_month:
            net_by_month[txn_key] += float(txn.get("amount", 0))

    balances: Dict[str, float] = {}
    running = ending_balance
    for key in reversed(month_keys):
        balances[key] = round(running, 2)
        running -= net_by_month[key]

    return [
        {"month": k, "balance": balances[k], "net": round(net_by_month[k], 2)}
        for k in month_keys
    ]
