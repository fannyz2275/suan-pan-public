from __future__ import annotations

import statistics
from dataclasses import dataclass
from itertools import combinations
from typing import List, Sequence

from app.engine.recurring.normalize import token_set, jaccard


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def regularity_score(gaps: Sequence[int]) -> float:
    if not gaps:
        return 0.0
    if len(gaps) == 1:
        return 1.0
    mu = statistics.mean(gaps)
    if mu == 0:
        return 0.0
    sigma = statistics.pstdev(gaps)
    cv = sigma / mu
    return 1.0 - _clamp(cv, 0.0, 1.0)


def amount_stability_score(amounts: Sequence[float]) -> float:
    if not amounts:
        return 0.0
    abs_amts = [abs(a) for a in amounts]
    if len(abs_amts) == 1:
        return 1.0
    mu = statistics.mean(abs_amts)
    if mu == 0:
        return 0.0
    sigma = statistics.pstdev(abs_amts)
    cv = sigma / mu
    return 1.0 - _clamp(cv, 0.0, 1.0)


def coverage_score(observed: int, period_days: int, window_days: int) -> float:
    expected = max(1, window_days // max(1, period_days))
    return min(observed / expected, 1.0)


def description_consistency_score(descriptions: Sequence[str]) -> float:
    if not descriptions:
        return 0.0
    if len(descriptions) == 1:
        return 1.0
    sets = [token_set(d) for d in descriptions]
    pairs = list(combinations(sets, 2))
    if not pairs:
        return 1.0
    return sum(jaccard(a, b) for a, b in pairs) / len(pairs)


@dataclass(frozen=True)
class ConfidenceInputs:
    gaps: List[int]
    amounts: List[float]
    observed_count: int
    period_days: int
    effective_window_days: int
    descriptions: List[str]
    labeled_match: bool


# Per spec §6: weights are 0.40 / 0.25 / 0.20 / 0.15 / 1.00.
_W_REGULARITY = 0.40
_W_AMOUNT = 0.25
_W_COVERAGE = 0.20
_W_DESC = 0.15
_W_LABELED = 1.00


def composite_confidence(inputs: ConfidenceInputs) -> float:
    raw = (
        _W_REGULARITY * regularity_score(inputs.gaps)
        + _W_AMOUNT * amount_stability_score(inputs.amounts)
        + _W_COVERAGE * coverage_score(
            inputs.observed_count, inputs.period_days, inputs.effective_window_days
        )
        + _W_DESC * description_consistency_score(inputs.descriptions)
        + _W_LABELED * (1.0 if inputs.labeled_match else 0.0)
    )
    return min(1.0, raw)
