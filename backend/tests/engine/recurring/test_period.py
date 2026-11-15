from datetime import date

import pytest

from app.engine.recurring.period import (
    map_median_to_frequency,
    infer_period,
    passes_minimum_occurrence_gate,
)
from app.engine.recurring.schema import Frequency


def test_recent_schedule_change_uses_consistent_tail_not_whole_history():
    from app.engine.recurring.period import infer_current_period
    dates = [date(2026, m, 1) for m in range(1, 8)] + [date(2026, 8, 14 + i*14) for i in range(2)] + [date(2026, 9, 11), date(2026, 9, 25)]
    assert infer_current_period(dates).frequency == Frequency.BIWEEKLY


def test_recent_biweekly_requires_enough_evidence():
    from app.engine.recurring.period import infer_current_period
    dates = [date(2026, m, 1) for m in range(1, 8)] + [date(2026, 8, 14), date(2026, 8, 28)]
    assert infer_current_period(dates).frequency == Frequency.MONTHLY


def test_fifteen_day_spacing_is_not_enough_to_assert_biweekly():
    from app.engine.recurring.period import infer_current_period
    dates = [date.fromordinal(date(2026, 1, 1).toordinal() + 15*i) for i in range(4)]
    assert infer_current_period(dates).frequency != Frequency.BIWEEKLY


def _d(y, m, day):
    return date(y, m, day)


def test_monthly_dates_map_to_monthly():
    dates = [_d(2026, m, 1) for m in range(1, 13)]
    period = infer_period(dates)
    assert period.median_gap_days == 30 or period.median_gap_days == 31
    assert period.frequency == Frequency.MONTHLY


def test_biweekly_maps_correctly():
    base = _d(2026, 1, 1)
    dates = [date.fromordinal(base.toordinal() + 14 * i) for i in range(6)]
    period = infer_period(dates)
    assert period.median_gap_days == 14
    assert period.frequency == Frequency.BIWEEKLY


def test_weekly_maps_correctly():
    base = _d(2026, 1, 1)
    dates = [date.fromordinal(base.toordinal() + 7 * i) for i in range(8)]
    period = infer_period(dates)
    assert period.median_gap_days == 7
    assert period.frequency == Frequency.WEEKLY


def test_quarterly_maps_correctly():
    dates = [_d(2025, 5, 1), _d(2025, 8, 1), _d(2025, 11, 1), _d(2026, 2, 1)]
    period = infer_period(dates)
    assert 89 <= period.median_gap_days <= 93
    assert period.frequency == Frequency.QUARTERLY


def test_irregular_returns_none_frequency():
    dates = [_d(2026, 1, 1), _d(2026, 1, 5), _d(2026, 3, 10), _d(2026, 3, 15)]
    period = infer_period(dates)
    assert period.frequency is None


def test_map_exact_edges():
    assert map_median_to_frequency(7) == Frequency.WEEKLY
    assert map_median_to_frequency(8) == Frequency.WEEKLY
    assert map_median_to_frequency(9) is None
    assert map_median_to_frequency(14) == Frequency.BIWEEKLY
    assert map_median_to_frequency(30) == Frequency.MONTHLY
    assert map_median_to_frequency(365) == Frequency.ANNUAL


@pytest.mark.parametrize("frequency, count, expected", [
    (Frequency.WEEKLY, 4, True),
    (Frequency.WEEKLY, 3, False),
    (Frequency.BIWEEKLY, 4, True),
    (Frequency.BIWEEKLY, 3, False),
    (Frequency.SEMI_MONTHLY, 3, True),
    (Frequency.MONTHLY, 3, True),
    (Frequency.MONTHLY, 2, False),
    (Frequency.QUARTERLY, 2, True),
    (Frequency.SEMI_ANNUAL, 2, True),
    (Frequency.ANNUAL, 2, True),
    (Frequency.ANNUAL, 1, False),
])
def test_minimum_occurrence_gate(frequency, count, expected):
    assert passes_minimum_occurrence_gate(frequency, count) is expected
