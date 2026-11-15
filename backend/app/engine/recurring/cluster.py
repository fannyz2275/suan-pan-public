from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, List, Literal

from app.engine.recurring.normalize import normalize_description, token_set, jaccard

_MERGE_JACCARD_THRESHOLD = 0.6
_MERGE_AMOUNT_TOLERANCE = 0.10  # ±10%


@dataclass
class CandidateCluster:
    normalized_key: str
    transaction_ids: List[str] = field(default_factory=list)
    descriptions: List[str] = field(default_factory=list)
    amounts: List[float] = field(default_factory=list)
    dates: List[date] = field(default_factory=list)


def _parse_date(v) -> date:
    if isinstance(v, date):
        return v
    return datetime.fromisoformat(str(v)).date()


def build_candidate_clusters(
    transactions: Iterable[dict],
    direction: Literal["income", "expense"],
) -> List[CandidateCluster]:
    # Filter by sign.
    sign_ok = (lambda a: a > 0) if direction == "income" else (lambda a: a < 0)
    rows = [t for t in transactions if sign_ok(float(t["amount"]))]

    # Primary bucketing by normalized key.
    buckets: dict[str, CandidateCluster] = {}
    for t in rows:
        key = normalize_description(t["description"])
        if not key:
            continue
        c = buckets.setdefault(key, CandidateCluster(normalized_key=key))
        c.transaction_ids.append(t["id"])
        c.descriptions.append(t["description"])
        c.amounts.append(float(t["amount"]))
        c.dates.append(_parse_date(t["date"]))

    clusters = list(buckets.values())

    # Merge neighboring buckets: token Jaccard on keys ≥ 0.6 AND median amounts within ±10%.
    merged: List[CandidateCluster] = []
    while clusters:
        head = clusters.pop(0)
        head_tokens = token_set(head.normalized_key)
        head_median = statistics.median([abs(a) for a in head.amounts])
        i = 0
        while i < len(clusters):
            other = clusters[i]
            other_tokens = token_set(other.normalized_key)
            other_median = statistics.median([abs(a) for a in other.amounts])
            amt_lo = head_median * (1 - _MERGE_AMOUNT_TOLERANCE)
            amt_hi = head_median * (1 + _MERGE_AMOUNT_TOLERANCE)
            if (
                jaccard(head_tokens, other_tokens) >= _MERGE_JACCARD_THRESHOLD
                and amt_lo <= other_median <= amt_hi
            ):
                head.transaction_ids.extend(other.transaction_ids)
                head.descriptions.extend(other.descriptions)
                head.amounts.extend(other.amounts)
                head.dates.extend(other.dates)
                clusters.pop(i)
            else:
                i += 1
        merged.append(head)

    return merged
