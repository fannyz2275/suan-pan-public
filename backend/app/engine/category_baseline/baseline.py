from __future__ import annotations

from datetime import date
from statistics import median
from typing import Dict, List, Tuple

from dateutil.relativedelta import relativedelta

from app.engine.category_baseline.schema import CategoryBaseline, Tier
from app.engine.category_baseline.tier import classify_tier

# Cap seasonal multipliers so a single anomalous year doesn't double-project.
_SEASONAL_MULTIPLIER_MIN = 0.5
_SEASONAL_MULTIPLIER_MAX = 2.0


def _mad(values: List[float], center: float) -> float:
    if not values:
        return 0.0
    return median([abs(v - center) for v in values])


def _trailing_median(monthly_totals: List[Tuple[str, float]], n: int = 3) -> float:
    """Median of the most recent n months. Series is sorted ascending by month."""
    if not monthly_totals:
        return 0.0
    tail = monthly_totals[-n:]
    return median([t for _, t in tail])


def _seasonal_multipliers(monthly_totals: List[Tuple[str, float]]) -> Dict[int, float]:
    """For each calendar month 1..12, mean(spend that month) / mean(spend all months).

    Computed only when we have ≥12 months of history. Result is clipped to
    [0.5, 2.0] per category to limit one-year-of-data overreach.
    """
    if not monthly_totals:
        return {}
    by_calendar_month: Dict[int, List[float]] = {}
    for ym, total in monthly_totals:
        month_num = int(ym.split("-")[1])
        by_calendar_month.setdefault(month_num, []).append(total)

    overall_mean = sum(t for _, t in monthly_totals) / len(monthly_totals)
    if overall_mean <= 0:
        return {}

    multipliers: Dict[int, float] = {}
    for m in range(1, 13):
        observations = by_calendar_month.get(m, [])
        if not observations:
            continue
        cal_mean = sum(observations) / len(observations)
        raw = cal_mean / overall_mean
        multipliers[m] = max(_SEASONAL_MULTIPLIER_MIN, min(_SEASONAL_MULTIPLIER_MAX, raw))
    return multipliers


def _next_month_str(today: date) -> str:
    return (today + relativedelta(months=1)).strftime("%Y-%m")


def compute_baselines(
    aggregated: Dict[str, List[Tuple[str, float]]],
    opted_out: bool = False,
    today: date | None = None,
) -> List[CategoryBaseline]:
    """Compute one CategoryBaseline per category in the aggregate.

    Categories with tier T1 are still returned so callers know they exist;
    median/mad will reflect whatever data is there but they shouldn't be used
    in projection.
    """
    if today is None:
        today = date.today()
    next_month_num = (today + relativedelta(months=1)).month

    out: List[CategoryBaseline] = []
    for category, series in aggregated.items():
        # Sort ascending by month string (lexicographic == chronological for "YYYY-MM").
        series_sorted = sorted(series, key=lambda r: r[0])
        months_observed = len(series_sorted)
        tier = classify_tier(months_observed, opted_out=opted_out)

        totals = [t for _, t in series_sorted]
        all_months_median = median(totals) if totals else 0.0
        mad = _mad(totals, all_months_median)
        trailing = _trailing_median(series_sorted)

        seasonal_multiplier: float | None = None
        next_expected = trailing
        if tier is Tier.T4:
            multipliers = _seasonal_multipliers(series_sorted)
            seasonal_multiplier = multipliers.get(next_month_num)
            if seasonal_multiplier is not None:
                next_expected = trailing * seasonal_multiplier

        out.append(CategoryBaseline(
            category=category,
            tier=tier,
            median_monthly=round(all_months_median, 2),
            mad=round(mad, 2),
            months_observed=months_observed,
            next_month_expected=round(next_expected, 2),
            seasonal_multiplier=round(seasonal_multiplier, 3) if seasonal_multiplier else None,
        ))
    return out


def project_baselined_months(
    baselines: List[CategoryBaseline],
    months: int,
    today: date | None = None,
    aggregated: Dict[str, List[Tuple[str, float]]] | None = None,
) -> List[Tuple[str, float, float, float]]:
    """For each of the next `months` months, return (month_str, expected, low, high).

    `low/high` are derived from MAD: T2 uses ±2×MAD, T3/T4 uses ±1×MAD.
    Aggregated is required for T4 seasonal multipliers per future month.
    """
    if today is None:
        today = date.today()
    aggregated = aggregated or {}

    result: List[Tuple[str, float, float, float]] = []
    for i in range(months):
        future = today + relativedelta(months=i + 1)
        ym = future.strftime("%Y-%m")
        cal_month = future.month

        expected_total = 0.0
        band_total_sq = 0.0  # variance-style sum so MADs add in quadrature
        for b in baselines:
            if b.tier is Tier.T1:
                continue
            base = _trailing_median(sorted(aggregated.get(b.category, []), key=lambda r: r[0]))
            if b.tier is Tier.T4:
                multipliers = _seasonal_multipliers(
                    sorted(aggregated.get(b.category, []), key=lambda r: r[0])
                )
                m = multipliers.get(cal_month)
                if m is not None:
                    base = base * m
            expected_total += base
            band_width = b.mad * (2 if b.tier is Tier.T2 else 1)
            band_total_sq += band_width ** 2

        band = band_total_sq ** 0.5
        result.append((
            ym,
            round(expected_total, 2),
            round(max(expected_total - band, 0.0), 2),
            round(expected_total + band, 2),
        ))
    return result
