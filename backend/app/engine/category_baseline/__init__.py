"""Per-category cashflow baselines computed from transaction history.

Used by /engine/cashflow to replace the single user-entered monthly_expenses
lump with category-level projections that handle variable but stable
spending (groceries, shopping). Falls back to the user's lump for
categories with insufficient data.

See docs/superpowers/specs/2026-04-27-category-baseline-projection-design.md.
"""
from app.engine.category_baseline.schema import (
    CategoryBaseline,
    ExpenseBudgetWarning,
    ProjectionMonth,
    Tier,
)
from app.engine.category_baseline.aggregate import aggregate_by_category_month
from app.engine.category_baseline.tier import classify_tier
from app.engine.category_baseline.baseline import compute_baselines
from app.engine.category_baseline.reconcile import reconcile_with_profile

__all__ = [
    "CategoryBaseline",
    "ExpenseBudgetWarning",
    "ProjectionMonth",
    "Tier",
    "aggregate_by_category_month",
    "classify_tier",
    "compute_baselines",
    "reconcile_with_profile",
]
