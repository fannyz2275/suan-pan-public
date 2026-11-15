from __future__ import annotations

import csv
import io
import logging
from datetime import date
from typing import Dict, Tuple

import httpx

logger = logging.getLogger(__name__)

_CACHE: Dict[Tuple[str, str, str], Dict[date, float]] = {}

_BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fetch_fred_series(series_id: str, from_date: date, to_date: date) -> Dict[date, float]:
    """Return {date: value} for a FRED series in the window. Returns {} on any failure.

    Free public endpoint; no API key. Cached within the process for repeat hits.
    """
    cache_key = (series_id, from_date.isoformat(), to_date.isoformat())
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    try:
        resp = httpx.get(
            _BASE_URL,
            params={"id": series_id, "cosd": from_date.isoformat(), "coed": to_date.isoformat()},
            timeout=10.0,
        )
    except Exception:
        logger.exception("FRED fetch failed for %s", series_id)
        _CACHE[cache_key] = {}
        return {}

    if resp.status_code != 200:
        logger.warning("FRED %s returned %d", series_id, resp.status_code)
        _CACHE[cache_key] = {}
        return {}

    out: Dict[date, float] = {}
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        raw_date = row.get("DATE") or row.get("date") or ""
        raw_val = row.get(series_id) or row.get(series_id.upper()) or ""
        if not raw_date or not raw_val or raw_val == ".":
            continue
        try:
            d = date.fromisoformat(raw_date)
            out[d] = float(raw_val)
        except (ValueError, TypeError):
            continue

    _CACHE[cache_key] = out
    return out
