from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.engine.category_baseline.schema import (
    CategoryBaseline,
    ExpenseBudgetWarning,
    Tier,
)

# When baselined total exceeds stated monthly_expenses by more than this,
# emit a budget warning so the UI can prompt the user to update their profile.
_BUDGET_WARNING_THRESHOLD = 0.20


def _baselined_historical_mean(
    baselines: List[CategoryBaseline],
    aggregated: Dict[str, List[Tuple[str, float]]],
) -> float:
    """Mean monthly total of categories that are tier ≥ T2.

    Used to subtract the historical share of baselined categories from the
    user's stated monthly_expenses so the residual covers only T1 / unbaselined
    spend.
    """
    total = 0.0
    months = 0
    monthly_sums: Dict[str, float] = {}
    for b in baselines:
        if b.tier is Tier.T1:
            continue
        for month, amount in aggregated.get(b.category, []):
            monthly_sums[month] = monthly_sums.get(month, 0.0) + amount
    if not monthly_sums:
        return 0.0
    return sum(monthly_sums.values()) / len(monthly_sums)


def reconcile_with_profile(
    baselines: List[CategoryBaseline],
    aggregated: Dict[str, List[Tuple[str, float]]],
    stated_monthly_expenses: Optional[float],
) -> Tuple[float, Optional[ExpenseBudgetWarning]]:
    """Compute the residual monthly_expenses to use alongside baselines.

    Returns (residual, warning):
      - residual: the lump-sum number to feed project_cashflow as
        monthly_expenses, covering everything not captured by baselines.
      - warning: present only when baselined total significantly exceeds the
        user's stated number, so the UI can nudge them to update.
    """
    historical_mean = _baselined_historical_mean(baselines, aggregated)

    if stated_monthly_expenses is None or stated_monthly_expenses <= 0:
        return 0.0, None

    residual = max(stated_monthly_expenses - historical_mean, 0.0)

    warning: Optional[ExpenseBudgetWarning] = None
    if historical_mean > stated_monthly_expenses * (1 + _BUDGET_WARNING_THRESHOLD):
        warning = ExpenseBudgetWarning(
            stated_monthly_expenses=round(stated_monthly_expenses, 2),
            baselined_total=round(historical_mean, 2),
            delta_pct=round(
                (historical_mean - stated_monthly_expenses) / stated_monthly_expenses,
                3,
            ),
        )
    return round(residual, 2), warning
