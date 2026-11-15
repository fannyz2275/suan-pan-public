from datetime import date

from app.engine.category_baseline.baseline import (
    compute_baselines,
    project_baselined_months,
)
from app.engine.category_baseline.schema import Tier


def test_t3_uses_trailing_three_month_median():
    aggregated = {
        "shopping": [
            ("2025-08", 200.0), ("2025-09", 100.0), ("2025-10", 1000.0),  # outlier
            ("2025-11", 400.0), ("2025-12", 410.0), ("2026-01", 420.0),
        ],
    }

    result = compute_baselines(aggregated, today=date(2026, 2, 1))

    [b] = result
    assert b.tier is Tier.T3
    # Trailing 3-month median: median(400, 410, 420) = 410
    assert b.next_month_expected == 410.0
    assert b.months_observed == 6
    assert b.seasonal_multiplier is None


def test_t2_with_three_months():
    aggregated = {"food": [("2025-11", 600), ("2025-12", 700), ("2026-01", 650)]}

    result = compute_baselines(aggregated, today=date(2026, 2, 1))

    [b] = result
    assert b.tier is Tier.T2
    assert b.next_month_expected == 650.0  # median(600, 700, 650)


def test_t1_when_under_three_months():
    aggregated = {"food": [("2025-12", 600), ("2026-01", 700)]}

    result = compute_baselines(aggregated, today=date(2026, 2, 1))

    [b] = result
    assert b.tier is Tier.T1


def test_opt_out_forces_t1_for_all():
    aggregated = {"shopping": [(f"2025-{m:02d}", 100.0) for m in range(1, 13)]}

    result = compute_baselines(aggregated, opted_out=True, today=date(2026, 2, 1))

    assert result[0].tier is Tier.T1
    assert result[0].seasonal_multiplier is None


def test_t4_applies_seasonal_multiplier():
    """December historically is 1.5× the annual average → next December
    projection is 1.5× the trailing-3-month median, capped at 2.0."""
    # 13 months: same $200 every month except December which is $400.
    series = []
    for ym, total in [
        ("2024-12", 400),
        ("2025-01", 200), ("2025-02", 200), ("2025-03", 200),
        ("2025-04", 200), ("2025-05", 200), ("2025-06", 200),
        ("2025-07", 200), ("2025-08", 200), ("2025-09", 200),
        ("2025-10", 200), ("2025-11", 200), ("2025-12", 400),
    ]:
        series.append((ym, float(total)))

    aggregated = {"shopping": series}
    # Project for January 2026: today is Dec 31 2025
    result = compute_baselines(aggregated, today=date(2025, 12, 31))

    [b] = result
    assert b.tier is Tier.T4
    # next month is January, January's seasonal_multiplier should be ~1.0
    assert b.seasonal_multiplier is not None
    assert 0.5 <= b.seasonal_multiplier <= 2.0


def test_seasonal_multiplier_capped_at_two():
    # 12 months where one month is 10× the others
    series = [(f"2025-{m:02d}", 100.0) for m in range(1, 12)]
    series.append(("2025-12", 5000.0))  # extreme December

    aggregated = {"shopping": series}
    # today = Nov 30 2025, so projected month is Dec 2025
    result = compute_baselines(aggregated, today=date(2025, 11, 30))

    [b] = result
    # Tier T4 (12 months) with December multiplier capped at 2.0
    assert b.tier is Tier.T4
    assert b.seasonal_multiplier is not None
    assert b.seasonal_multiplier <= 2.0


def test_project_baselined_months_sums_categories():
    aggregated = {
        "shopping": [("2025-11", 400), ("2025-12", 400), ("2026-01", 400)],
        "food": [("2025-11", 600), ("2025-12", 600), ("2026-01", 600)],
    }
    baselines = compute_baselines(aggregated, today=date(2026, 1, 31))

    months = project_baselined_months(
        baselines, months=2, today=date(2026, 1, 31), aggregated=aggregated
    )

    assert len(months) == 2
    [first, second] = months
    assert first[0] == "2026-02"
    assert first[1] == 1000.0  # 400 + 600
    assert second[0] == "2026-03"


def test_project_baselined_months_skips_t1_categories():
    aggregated = {
        "shopping": [("2025-11", 400), ("2025-12", 400), ("2026-01", 400)],
        "food": [("2026-01", 600)],  # only 1 month → T1
    }
    baselines = compute_baselines(aggregated, today=date(2026, 1, 31))

    months = project_baselined_months(
        baselines, months=1, today=date(2026, 1, 31), aggregated=aggregated
    )

    [first] = months
    # Only shopping (T2) contributes; food is T1
    assert first[1] == 400.0
