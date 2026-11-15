from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence

from app.engine.recurring.schema import Frequency

_BUCKETS: list[tuple[int, int, Frequency]] = [
    (6, 8, Frequency.WEEKLY),
    (13, 15, Frequency.BIWEEKLY),
    (28, 32, Frequency.MONTHLY),
    (88, 95, Frequency.QUARTERLY),
    (180, 190, Frequency.SEMI_ANNUAL),
    (355, 375, Frequency.ANNUAL),
]

_MIN_OCCURRENCES: dict[Frequency, int] = {
    Frequency.WEEKLY: 4,
    Frequency.BIWEEKLY: 4,
    Frequency.SEMI_MONTHLY: 3,
    Frequency.MONTHLY: 3,
    Frequency.QUARTERLY: 2,
    Frequency.SEMI_ANNUAL: 2,
    Frequency.ANNUAL: 2,
}


@dataclass(frozen=True)
class PeriodResult:
    median_gap_days: Optional[int]
    gaps: List[int]
    frequency: Optional[Frequency]


def map_median_to_frequency(median_days: int) -> Optional[Frequency]:
    for lo, hi, freq in _BUCKETS:
        if lo <= median_days <= hi:
            return freq
    return None


def infer_period(dates: Sequence[date]) -> PeriodResult:
    if len(dates) < 2:
        return PeriodResult(median_gap_days=None, gaps=[], frequency=None)
    ordered = sorted(dates)
    gaps = [(ordered[i + 1] - ordered[i]).days for i in range(len(ordered) - 1)]
    median = int(round(statistics.median(gaps)))
    return PeriodResult(
        median_gap_days=median,
        gaps=gaps,
        frequency=map_median_to_frequency(median),
    )


def passes_minimum_occurrence_gate(frequency: Frequency, count: int) -> bool:
    return count >= _MIN_OCCURRENCES[frequency]


def infer_current_period(dates: Sequence[date]) -> PeriodResult:
    """Prefer a sustained recent schedule over a mixed whole-history median."""
    baseline = infer_period(dates)
    if baseline.frequency == Frequency.BIWEEKLY and baseline.gaps.count(14) < 2:
        baseline = PeriodResult(baseline.median_gap_days, baseline.gaps, None)
    if len(dates) < 4:
        return baseline
    recent = infer_period(sorted(dates)[-4:])
    if recent.frequency is None or recent.frequency == baseline.frequency:
        return baseline
    if not all(map_median_to_frequency(gap) == recent.frequency for gap in recent.gaps):
        return baseline
    # Avoid relabeling calendar twice-monthly payments from a median near 14.
    if recent.frequency == Frequency.BIWEEKLY and recent.gaps.count(14) < 2:
        return baseline
    return recent
