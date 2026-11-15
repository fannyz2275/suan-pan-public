from __future__ import annotations

from collections import defaultdict
from typing import Iterable, List, Literal, Mapping

Dimension = Literal["asset_class", "sector", "region", "country"]


def _label_for(ref: dict | None, dimension: Dimension) -> str:
    if not ref:
        return "Other"
    val = ref.get(dimension)
    return val if val else "Other"


def compute_exposure(
    holdings: Iterable[dict],
    references: Mapping[str, dict],
    dimension: Dimension,
) -> List[dict]:
    """Aggregate holding market_value by dimension.

    For sector/region, ETF look_through (top-10) distributes weighted market_value
    to underlying tickers' label; the residual stays at the ETF's own label.
    asset_class never uses look-through.
    """
    buckets: dict[str, float] = defaultdict(float)

    for h in holdings:
        ticker = h["ticker"]
        mv = float(h["market_value"])
        ref = references.get(ticker)

        use_look_through = (
            dimension in ("sector", "region", "country")
            and ref is not None
            and ref.get("look_through")
        )

        if not use_look_through:
            buckets[_label_for(ref, dimension)] += mv
            continue

        weights_sum = 0.0
        for item in ref["look_through"]:
            child_ticker = item["ticker"]
            weight = float(item["weight"])
            child_ref = references.get(child_ticker)
            buckets[_label_for(child_ref, dimension)] += mv * weight
            weights_sum += weight

        residual = max(0.0, 1.0 - weights_sum)
        if residual > 0:
            buckets[_label_for(ref, dimension)] += mv * residual

    total = sum(buckets.values()) or 1.0
    out = [
        {"label": label, "market_value": round(val, 2), "percent": round(val / total * 100, 4)}
        for label, val in buckets.items()
    ]
    out.sort(key=lambda s: s["market_value"], reverse=True)
    return out
