from datetime import date

from app.engine.category_baseline.baseline import compute_baselines
from app.engine.category_baseline.reconcile import reconcile_with_profile


def test_residual_subtracts_baselined_historical_share():
    """User says they spend $2000/mo total. History shows shopping averages
    $400/mo. Residual should be $1600/mo for everything else."""
    aggregated = {
        "shopping": [(f"2025-{m:02d}", 400.0) for m in range(7, 13)],
    }
    baselines = compute_baselines(aggregated, today=date(2025, 12, 31))

    residual, warning = reconcile_with_profile(
        baselines, aggregated, stated_monthly_expenses=2000.0
    )

    assert residual == 1600.0
    assert warning is None


def test_residual_floors_at_zero():
    aggregated = {
        "shopping": [(f"2025-{m:02d}", 1500.0) for m in range(1, 13)],
    }
    baselines = compute_baselines(aggregated, today=date(2025, 12, 31))

    residual, warning = reconcile_with_profile(
        baselines, aggregated, stated_monthly_expenses=1000.0
    )

    assert residual == 0.0
    assert warning is not None
    # 1500 vs stated 1000 = 50% over, exceeds 20% threshold
    assert warning.delta_pct == 0.5


def test_no_warning_when_under_threshold():
    aggregated = {
        "shopping": [(f"2025-{m:02d}", 1100.0) for m in range(1, 13)],
    }
    baselines = compute_baselines(aggregated, today=date(2025, 12, 31))

    # 1100 vs 1000 = 10% over, under 20% threshold
    residual, warning = reconcile_with_profile(
        baselines, aggregated, stated_monthly_expenses=1000.0
    )

    assert warning is None


def test_null_monthly_expenses_returns_zero_residual():
    aggregated = {
        "shopping": [(f"2025-{m:02d}", 400.0) for m in range(1, 7)],
    }
    baselines = compute_baselines(aggregated, today=date(2025, 7, 31))

    residual, warning = reconcile_with_profile(
        baselines, aggregated, stated_monthly_expenses=None
    )

    assert residual == 0.0
    assert warning is None


def test_t1_categories_dont_count_toward_baselined_total():
    aggregated = {
        "shopping": [(f"2025-{m:02d}", 400.0) for m in range(7, 13)],  # T3
        "rare_category": [("2025-12", 999.0)],                          # T1, ignored
    }
    baselines = compute_baselines(aggregated, today=date(2025, 12, 31))

    residual, warning = reconcile_with_profile(
        baselines, aggregated, stated_monthly_expenses=1500.0
    )

    # Only shopping counts → 1500 - 400 = 1100
    assert residual == 1100.0
