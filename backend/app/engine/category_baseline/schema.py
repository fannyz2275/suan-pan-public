from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Tier(str, Enum):
    """Per-category projection tier.

    T1 = insufficient data or opted out (folded into residual lump).
    T2 = 3-4 months observed (trailing median, wide band).
    T3 = 5-11 months observed (trailing median, normal band).
    T4 = 12+ months observed (trailing median × seasonal multiplier).
    """
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class CategoryBaseline(BaseModel):
    category: str
    tier: Tier
    median_monthly: float
    mad: float
    months_observed: int
    next_month_expected: float
    seasonal_multiplier: Optional[float] = None


class ProjectionMonth(BaseModel):
    """Projected expense band for one future month, summed over baselined categories."""
    month: str  # "YYYY-MM"
    expected: float
    low: float
    high: float


class ExpenseBudgetWarning(BaseModel):
    stated_monthly_expenses: float
    baselined_total: float
    delta_pct: float
