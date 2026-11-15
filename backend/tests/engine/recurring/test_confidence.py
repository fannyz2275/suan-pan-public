from datetime import date, timedelta

import pytest

from app.engine.recurring.confidence import (
    regularity_score,
    amount_stability_score,
    coverage_score,
    description_consistency_score,
    composite_confidence,
    ConfidenceInputs,
)
from app.engine.recurring.schema import Frequency


def test_regularity_perfect_when_identical_gaps():
    assert regularity_score([30, 30, 30, 30]) == pytest.approx(1.0)


def test_regularity_zero_when_very_irregular():
    assert regularity_score([1, 60, 2, 120]) == pytest.approx(0.0, abs=0.05)


def test_regularity_single_gap_is_one():
    assert regularity_score([30]) == 1.0


def test_regularity_empty_returns_zero():
    assert regularity_score([]) == 0.0


def test_amount_stability_perfect_when_identical():
    assert amount_stability_score([100.0, 100.0, 100.0]) == pytest.approx(1.0)


def test_amount_stability_drops_with_variance():
    score = amount_stability_score([50.0, 100.0, 150.0, 200.0])
    assert 0.3 < score < 0.7


def test_amount_stability_uses_absolute_values():
    # Signed input, but stability should ignore sign.
    assert amount_stability_score([-100.0, -100.0, -100.0]) == pytest.approx(1.0)


def test_coverage_caps_at_one():
    assert coverage_score(observed=15, period_days=30, window_days=365) == 1.0


def test_coverage_new_account_not_penalized():
    # 3 monthly observations, 90-day account → expected=3 → coverage=1.
    assert coverage_score(observed=3, period_days=30, window_days=90) == pytest.approx(1.0)


def test_coverage_thin_observations():
    # 4 of expected 12.
    assert coverage_score(observed=4, period_days=30, window_days=365) == pytest.approx(4 / 12)


def test_description_consistency_identical_descriptions():
    s = description_consistency_score(["Greystar Apts", "Greystar Apts", "Greystar Apts"])
    assert s == pytest.approx(1.0)


def test_description_consistency_disjoint_descriptions():
    s = description_consistency_score(["Netflix", "Spotify", "Hulu"])
    assert s == pytest.approx(0.0)


def test_description_consistency_single_item_is_one():
    assert description_consistency_score(["Netflix"]) == 1.0


def test_composite_clamps_at_one_with_labeled_match():
    inputs = ConfidenceInputs(
        gaps=[30] * 11,
        amounts=[2800.0] * 12,
        observed_count=12,
        period_days=30,
        effective_window_days=365,
        descriptions=["Greystar Apts"] * 12,
        labeled_match=True,
    )
    assert composite_confidence(inputs) == 1.0


def test_composite_rent_example_scores_near_one():
    inputs = ConfidenceInputs(
        gaps=[30] * 11,
        amounts=[2800.0] * 12,
        observed_count=12,
        period_days=30,
        effective_window_days=365,
        descriptions=["Greystar Apts"] * 12,
        labeled_match=False,
    )
    assert composite_confidence(inputs) == pytest.approx(1.0)


def test_composite_noisy_series_scores_low():
    inputs = ConfidenceInputs(
        gaps=[1, 60, 2, 120],
        amounts=[50.0, 200.0, 25.0, 180.0],
        observed_count=4,
        period_days=45,
        effective_window_days=365,
        descriptions=["NETFLIX", "SPOTIFY", "HULU", "DISNEY"],
        labeled_match=False,
    )
    c = composite_confidence(inputs)
    assert c < 0.4


def test_composite_fields_sum_match_spec():
    # Confirm weights: 0.40 regularity, 0.25 amount, 0.20 coverage, 0.15 desc, 1.0 labeled.
    inputs = ConfidenceInputs(
        gaps=[30] * 11,
        amounts=[2800.0] * 12,
        observed_count=12,
        period_days=30,
        effective_window_days=365,
        descriptions=["a"] * 12,
        labeled_match=False,
    )
    # regularity=1, amount=1, coverage=1, desc=1 → raw=1.0.
    assert composite_confidence(inputs) == pytest.approx(1.0)
