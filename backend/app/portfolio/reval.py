from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Mapping, Tuple


def _most_recent_price(
    ticker: str,
    as_of: date,
    prices: Mapping[Tuple[str, date], float],
    max_staleness_days: int,
) -> float | None:
    """Return the most recent price <= as_of, or None if none within staleness window."""
    earliest = as_of - timedelta(days=max_staleness_days)
    best: Tuple[date, float] | None = None
    for (t, d), p in prices.items():
        if t != ticker:
            continue
        if d > as_of or d < earliest:
            continue
        if best is None or d > best[0]:
            best = (d, p)
    return best[1] if best else None


def revalue_at(
    holdings: Iterable[dict],
    as_of: date,
    prices: Mapping[Tuple[str, date], float],
    cash: float,
    max_staleness_days: int = 7,
) -> float:
    """Total portfolio value on as_of given holdings (qty × price) + cash.

    For each holding, uses the price exactly on as_of if present, else the most
    recent price within max_staleness_days. If neither, the holding contributes 0.
    """
    total = float(cash)
    for h in holdings:
        ticker = h["ticker"]
        qty = float(h["quantity"])
        price = _most_recent_price(ticker, as_of, prices, max_staleness_days)
        if price is None:
            continue
        total += qty * price
    return total


def _coerce_date(d: "date | str") -> date:
    """Accept a date or ISO string and always return a date."""
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


def _snapshot_as_of(snapshots: List[dict], on: date) -> dict | None:
    """Return the snapshot with the largest snapshot_date <= on, or None."""
    best: dict | None = None
    for s in snapshots:
        sd = _coerce_date(s["snapshot_date"])
        if sd > on:
            continue
        if best is None or sd > _coerce_date(best["snapshot_date"]):
            best = s
    return best


def timeseries(
    snapshots: List[dict],
    prices: Mapping[Tuple[str, date], float],
    from_date: date,
    to_date: date,
    max_staleness_days: int = 7,
) -> List[dict]:
    """Compute (date, total_value) pairs for every day in [from_date, to_date].

    Each day uses the most recent snapshot on/before that day; holdings are
    revalued via revalue_at. If no snapshot anchors `from_date`, the series
    starts from the earliest snapshot in window — otherwise a user whose
    first import is dated mid-window would see an empty chart.
    """
    if not snapshots:
        return []

    if _snapshot_as_of(snapshots, from_date) is None:
        first_snap_date = min(_coerce_date(s["snapshot_date"]) for s in snapshots)
        if first_snap_date > to_date:
            return []
        cur = first_snap_date
    else:
        cur = from_date

    out: List[dict] = []
    while cur <= to_date:
        snap = _snapshot_as_of(snapshots, cur)
        if snap is not None:
            tv = revalue_at(
                snap["holdings"],
                cur,
                prices,
                cash=float(snap.get("cash_value", 0) or 0),
                max_staleness_days=max_staleness_days,
            )
            out.append({"date": cur, "total_value": tv})
        cur += timedelta(days=1)
    return out
