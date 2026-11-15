# backend/app/portfolio/reference.py
from __future__ import annotations

import logging
import os
from datetime import date as _date, datetime as _dt, timedelta as _td, timezone as _tz
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# How long a known price-lookup failure stays cached before we retry yfinance.
_MISS_TTL_DAYS = 7

_DEVELOPED = frozenset({
    "Canada", "United Kingdom", "Germany", "France", "Switzerland",
    "Netherlands", "Sweden", "Norway", "Denmark", "Finland", "Belgium",
    "Italy", "Spain", "Austria", "Ireland", "Australia", "New Zealand",
    "Japan", "Singapore", "Hong Kong", "South Korea", "Israel",
})

_EMERGING = frozenset({
    "China", "Taiwan", "India", "Brazil", "Mexico", "South Africa",
    "Russia", "Turkey", "Indonesia", "Thailand", "Malaysia",
    "Philippines", "Vietnam", "Poland", "Czech Republic", "Hungary",
    "Chile", "Argentina", "Colombia", "Peru", "Egypt", "Saudi Arabia",
    "United Arab Emirates", "Qatar", "Kuwait",
})

_QUOTETYPE_TO_TYPE = {
    "EQUITY": "stock",
    "ETF": "etf",
    "MUTUALFUND": "mutual_fund",
    "INDEX": "etf",
    "CRYPTOCURRENCY": "crypto",
    "CURRENCY": "cash",
}

_TYPE_TO_ASSET_CLASS = {
    "stock": "equity",
    "etf": "equity",
    "mutual_fund": "equity",
    "crypto": "crypto",
    "cash": "cash",
}


def country_to_region(country: Optional[str]) -> str:
    if not country:
        return "Global"
    if country == "United States":
        return "US"
    if country in _DEVELOPED:
        return "Developed"
    if country in _EMERGING:
        return "Emerging"
    return "Global"


def _extract_top_holdings(funds_data: Any) -> Optional[List[Dict[str, Any]]]:
    """Pull top-10 (ticker, weight) pairs from yfinance funds_data, if present."""
    if funds_data is None:
        return None
    raw = getattr(funds_data, "top_holdings", None)
    if raw is None:
        return None
    out: List[Dict[str, Any]] = []
    if isinstance(raw, pd.DataFrame):
        raw = [
            {"symbol": symbol, "weight": row.get("Holding Percent")}
            for symbol, row in raw.head(10).iterrows()
        ]
    for item in list(raw)[:10]:
        sym = item.get("symbol") if isinstance(item, dict) else None
        weight = item.get("weight") if isinstance(item, dict) else None
        if sym and weight is not None and not _isnan(float(weight)):
            out.append({"ticker": sym, "weight": float(weight)})
    return out or None


def enrich_ticker(ticker: str) -> Dict[str, Any]:
    """Fetch metadata for a ticker via yfinance.

    Returns a dict shaped to insert into security_reference. Failures degrade
    to asset_class='other' rather than raising.
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception:
        logger.exception("yfinance enrichment failed for %s", ticker)
        info = {}

    quote_type = (info.get("quoteType") or "").upper()
    sec_type = _QUOTETYPE_TO_TYPE.get(quote_type, "other")
    asset_class = _TYPE_TO_ASSET_CLASS.get(sec_type, "other")
    sector = info.get("sector") if sec_type == "stock" else None
    country = info.get("country")
    look_through = None
    if sec_type in {"etf", "mutual_fund"}:
        try:
            look_through = _extract_top_holdings(getattr(t, "funds_data", None))
        except Exception:
            logger.exception("yfinance holdings fetch failed for %s", ticker)

    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName"),
        "security_type": sec_type,
        "asset_class": asset_class,
        "sector": sector,
        "country": country,
        "region": country_to_region(country),
        "look_through": look_through,
        "enrichment_source": "yfinance",
    }


def get_prices(
    db: Any,
    tickers: Iterable[str],
    from_date: _date,
    to_date: _date,
) -> Dict[Tuple[str, _date], float]:
    """Return a {(ticker, date): close} map for [from_date, to_date].

    Reads from the security_prices cache, then fills any missing tickers via
    yfinance.download (single multi-ticker call) and persists the new rows.
    Tickers that yfinance can't resolve are recorded in security_price_misses
    so subsequent calls skip them until the TTL expires.
    """
    out, _ = _get_prices_with_misses(db, tickers, from_date, to_date)
    return out


def get_prices_with_misses(
    db: Any,
    tickers: Iterable[str],
    from_date: _date,
    to_date: _date,
) -> Tuple[Dict[Tuple[str, _date], float], List[str]]:
    """Same as get_prices but also returns the tickers that resolved to no
    price data — either because yfinance just failed for them or because they
    are still inside the negative-cache TTL.
    """
    return _get_prices_with_misses(db, tickers, from_date, to_date)


def _get_prices_with_misses(
    db: Any,
    tickers: Iterable[str],
    from_date: _date,
    to_date: _date,
) -> Tuple[Dict[Tuple[str, _date], float], List[str]]:
    tickers = list(set(tickers))
    if not tickers:
        return {}, []

    cached_rows = (
        db.table("security_prices")
        .select("*")
        .in_("ticker", tickers)
        .gte("date", from_date.isoformat())
        .lte("date", to_date.isoformat())
        .execute()
        .data
    )
    out: Dict[Tuple[str, _date], float] = {}
    seen_tickers: set[str] = set()
    for r in cached_rows:
        d = _date.fromisoformat(r["date"]) if isinstance(r["date"], str) else r["date"]
        out[(r["ticker"], d)] = float(r["close"])
        seen_tickers.add(r["ticker"])

    candidates = [t for t in tickers if t not in seen_tickers]
    if not candidates:
        return out, []

    fresh_misses = _load_fresh_misses(db, candidates)
    missing = [t for t in candidates if t not in fresh_misses]
    unpriced: set[str] = set(fresh_misses)
    if not missing:
        return out, sorted(unpriced)

    fetched: set[str] = set()
    yf_exception = False
    if missing:
        try:
            df = yf.download(
                tickers=missing, start=from_date.isoformat(),
                end=(to_date + _td(days=1)).isoformat(),  # yfinance end is exclusive
                progress=False, group_by="ticker", auto_adjust=False,
            )
        except Exception:
            logger.exception("yfinance bulk price fetch failed")
            yf_exception = True
            df = None

        rows_to_insert: list[dict] = []
        if not yf_exception and df is not None and not df.empty:
            for ticker in missing:
                if isinstance(df.columns, pd.MultiIndex):
                    if ticker not in df.columns.get_level_values(0):
                        continue
                    sub = df[ticker]
                elif len(missing) == 1:
                    sub = df
                else:
                    continue
                for ts, row in sub.iterrows():
                    close = row.get("Close")
                    if close is None or _isnan(close):
                        continue
                    d = ts.date() if hasattr(ts, "date") else ts
                    out[(ticker, d)] = float(close)
                    fetched.add(ticker)
                    rows_to_insert.append({"ticker": ticker, "date": d.isoformat(), "close": float(close)})

        if rows_to_insert:
            try:
                db.table("security_prices").upsert(rows_to_insert).execute()
            except Exception:
                logger.exception("price cache upsert failed")

    failed_now = [t for t in missing if t not in fetched]

    if failed_now:
        _record_misses(db, failed_now, "no_data_returned")
        unpriced.update(failed_now)

    return out, sorted(unpriced)


def _load_fresh_misses(db: Any, tickers: List[str]) -> set[str]:
    """Return the subset of `tickers` whose last failed attempt is still inside
    the TTL window — those should be skipped instead of re-tried.
    """
    if not tickers:
        return set()
    cutoff = (_dt.now(_tz.utc) - _td(days=_MISS_TTL_DAYS)).isoformat()
    try:
        rows = (
            db.table("security_price_misses")
            .select("ticker,last_attempt_at")
            .in_("ticker", tickers)
            .gte("last_attempt_at", cutoff)
            .execute()
            .data
            or []
        )
    except Exception:
        # Table may be absent in tests / pre-migration envs; degrade quietly.
        logger.debug("security_price_misses lookup failed", exc_info=True)
        return set()
    return {r["ticker"] for r in rows}


def ensure_enriched(db: Any, tickers: Iterable[str], max_per_call: int = 8) -> int:
    """Backfill security_reference for tickers missing fundamentals.

    Targets rows lacking country/look_through, using Yahoo Finance metadata.
    Capped per call; incomplete rows are retried after the enrichment TTL.
    Returns the number of tickers actually re-enriched this call.
    """
    # Keep existing API tests independent of live market-data requests.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    tickers = list({t for t in tickers if t})
    if not tickers:
        return 0
    rows = (
        db.table("security_reference")
        .select("ticker,country,sector,look_through,enriched_at")
        .in_("ticker", tickers)
        .execute()
        .data
        or []
    )
    by_ticker = {r["ticker"]: r for r in rows}
    needs: list[str] = []
    for t in tickers:
        r = by_ticker.get(t)
        if r is None:
            needs.append(t)
            continue
        # Treat a row as "thin" when both country and look_through are absent —
        # those are the dimensions the new exposures and look-through table
        # rely on. Only retry rows that still need metadata.
        if not r.get("country") and not r.get("look_through"):
            attempted_at = r.get("enriched_at")
            if attempted_at:
                try:
                    attempted_at = _dt.fromisoformat(attempted_at.replace("Z", "+00:00"))
                    if attempted_at.tzinfo is None:
                        attempted_at = attempted_at.replace(tzinfo=_tz.utc)
                    if attempted_at > _dt.now(_tz.utc) - _td(days=_MISS_TTL_DAYS):
                        continue
                except (TypeError, ValueError):
                    pass
            needs.append(t)
    if not needs:
        return 0

    todo = needs[:max_per_call]
    logger.info("Re-enriching %d security_reference row(s): %s", len(todo), todo)
    enriched_at = _dt.now(_tz.utc).isoformat()
    payload: list[dict] = []
    for t in todo:
        try:
            row = enrich_ticker(t)
        except Exception:
            logger.exception("enrich_ticker failed for %s", t)
            continue
        row["enriched_at"] = enriched_at
        payload.append(row)
    if not payload:
        return 0
    try:
        db.table("security_reference").upsert(payload, on_conflict="ticker").execute()
    except Exception:
        logger.exception("security_reference upsert failed")
        return 0
    return len(payload)


def _record_misses(db: Any, tickers: List[str], reason: str) -> None:
    if not tickers:
        return
    now_iso = _dt.now(_tz.utc).isoformat()
    rows = [{"ticker": t, "last_attempt_at": now_iso, "reason": reason} for t in tickers]
    try:
        db.table("security_price_misses").upsert(rows).execute()
    except Exception:
        logger.debug("security_price_misses upsert failed", exc_info=True)


def _isnan(x: float) -> bool:
    return x != x
