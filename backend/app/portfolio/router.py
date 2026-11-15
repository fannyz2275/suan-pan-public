import logging
from datetime import date, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.auth.middleware import get_current_user
from app.db import get_admin_db
from app.imports.parser import extract_csv_text, extract_pdf_text
from app.plaid.router import _plaid_client
from app.portfolio import exposure as exposure_engine
from app.portfolio import reval as reval_engine
from app.portfolio import reference as ref_module
from app.portfolio import schemas, snapshots
from app.portfolio.attribution import compute_attribution
from app.portfolio.fred import fetch_fred_series
from app.portfolio.plaid_sync import sync_plaid_investments
from app.portfolio.statement_parser import parse_investment_statement

logger = logging.getLogger(__name__)

_STATEMENT_EXTENSIONS = {".pdf", ".csv", ".txt"}
_STATEMENT_MAX_MB = 10

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _build_plaid_client():
    """Indirection so tests can patch easily."""
    return _plaid_client()


def _assert_owns_account(
    db,
    user_id: str,
    account_id: str,
    *,
    expected_types: list[str] | None = None,
) -> None:
    rows = (
        db.table("accounts").select("id, type")
        .eq("id", account_id).eq("user_id", user_id)
        .limit(1).execute().data
    )
    if not rows:
        raise HTTPException(404, "account not found")
    if expected_types is not None and rows[0].get("type") not in expected_types:
        raise HTTPException(400, f"account type must be one of: {expected_types}")


@router.post("/sync/plaid")
async def sync_plaid(user=Depends(get_current_user)):
    db = get_admin_db()
    client = _build_plaid_client()
    try:
        snaps = sync_plaid_investments(db, user_id=str(user.id), plaid_client=client)
    except Exception:
        logger.exception("Plaid investments sync failed")
        raise HTTPException(502, "Plaid sync failed")
    return {"snapshots_written": len(snaps)}


@router.post("/snapshot/manual", response_model=schemas.SnapshotOut)
async def create_manual_snapshot(
    body: schemas.ManualSnapshotIn,
    user=Depends(get_current_user),
):
    db = get_admin_db()
    _assert_owns_account(db, str(user.id), str(body.account_id))
    row = snapshots.create_manual_snapshot(
        db,
        user_id=str(user.id),
        account_id=str(body.account_id),
        snapshot_date=body.snapshot_date,
        cash_value=body.cash_value,
        holdings=[h.model_dump() for h in body.holdings],
    )
    return _to_snapshot_out(row)


def _to_snapshot_out(row: dict) -> schemas.SnapshotOut:
    holdings = row.get("holdings") or []
    total = float(row["total_value"]) or 1.0
    out_holdings = [
        schemas.HoldingOut(
            ticker=h["ticker"],
            quantity=float(h["quantity"]),
            price=float(h["price"]),
            market_value=float(h["market_value"]),
            percent=round(float(h["market_value"]) / total * 100, 4),
            cost_basis=h.get("cost_basis"),
            unrealized_gain=h.get("unrealized_gain"),
        )
        for h in holdings
    ]
    return schemas.SnapshotOut(
        id=row["id"],
        account_id=row["account_id"],
        snapshot_date=row["snapshot_date"],
        source=row["source"],
        total_value=float(row["total_value"]),
        cash_value=float(row["cash_value"]),
        holdings=out_holdings,
        created_at=row["created_at"],
    )


@router.get("/value", response_model=schemas.PortfolioValueOut)
async def get_portfolio_value(
    account_id: Optional[UUID] = None,
    user=Depends(get_current_user),
):
    """Total portfolio value across the user's investment accounts (or a single
    account if `account_id` is given). Sums the latest non-superseded snapshot
    per account. Returns the most recent snapshot_date as `as_of`.
    """
    db = get_admin_db()
    if account_id is not None:
        _assert_owns_account(db, str(user.id), str(account_id))
        account_ids = [str(account_id)]
    else:
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", str(user.id))
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]

    total = 0.0
    accounts_with_snapshot = 0
    as_of: Optional[date] = None
    for aid in account_ids:
        snap = snapshots.get_latest_snapshot(db, account_id=aid)
        if not snap:
            continue
        snap_total = float(snap.get("total_value") or 0)
        total += snap_total
        accounts_with_snapshot += 1
        snap_date = snap.get("snapshot_date")
        if isinstance(snap_date, str):
            snap_date = date.fromisoformat(snap_date)
        if snap_date and (as_of is None or snap_date > as_of):
            as_of = snap_date

        # Self-heal: keep accounts.balance in sync with the latest snapshot so
        # the Accounts tree, net-worth roll-up, and KPI engines all see the
        # imported portfolio. Pre-fix imports left this stuck at the
        # account's seed balance (often zero) and the breakdown looked empty.
        _reconcile_account_balance(db, str(user.id), aid, snap_total)

    return schemas.PortfolioValueOut(
        total_value=total,
        as_of=as_of,
        account_count=accounts_with_snapshot,
    )


def _reconcile_account_balance(db, user_id: str, account_id: str, target: float) -> None:
    from app.finance.balance_history import cache_patch, record_history

    rows = (
        db.table("accounts")
        .select("id,balance,balance_updated_at,created_at")
        .eq("id", account_id).eq("user_id", user_id)
        .limit(1).execute().data or []
    )
    if not rows:
        return
    acct = rows[0]
    cur = acct.get("balance")
    if cur is not None and abs(float(cur) - target) < 0.005:
        return

    update_payload: dict = {"balance": target}
    update_payload.update(cache_patch(acct, target))
    db.table("accounts").update(update_payload).eq("id", account_id).execute()
    record_history(
        db, account_id=account_id, user_id=user_id,
        balance=target, source="file_import",
    )


@router.get("/holdings", response_model=List[schemas.HoldingOut])
async def get_holdings(
    account_id: Optional[UUID] = None,
    user=Depends(get_current_user),
):
    db = get_admin_db()
    try:
        snapshots.ensure_today_snapshot(
            db, user_id=str(user.id), plaid_client_factory=_build_plaid_client,
        )
    except Exception:
        logger.exception("Lazy Plaid sync failed; continuing with stale data")
    if account_id is not None:
        _assert_owns_account(db, str(user.id), str(account_id))
    if account_id is None:
        # Household roll-up: aggregate latest snapshot per investment account.
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", str(user.id))
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]
    else:
        account_ids = [str(account_id)]

    aggregated: dict[str, dict] = {}
    grand_total = 0.0
    for aid in account_ids:
        snap = snapshots.get_latest_snapshot(db, account_id=aid)
        if not snap:
            continue
        for h in snap["holdings"]:
            t = h["ticker"]
            mv = float(h["market_value"])
            grand_total += mv
            if t in aggregated:
                aggregated[t]["quantity"] += float(h["quantity"])
                aggregated[t]["market_value"] += mv
            else:
                aggregated[t] = {
                    "ticker": t,
                    "quantity": float(h["quantity"]),
                    "price": float(h["price"]),
                    "market_value": mv,
                    "cost_basis": h.get("cost_basis"),
                    "unrealized_gain": h.get("unrealized_gain"),
                }

    if grand_total <= 0:
        return []
    return [
        schemas.HoldingOut(
            ticker=v["ticker"],
            quantity=v["quantity"],
            price=v["price"],
            market_value=v["market_value"],
            percent=round(v["market_value"] / grand_total * 100, 4),
            cost_basis=v["cost_basis"],
            unrealized_gain=v["unrealized_gain"],
        )
        for v in sorted(aggregated.values(), key=lambda x: x["market_value"], reverse=True)
    ]


@router.get("/exposure", response_model=List[schemas.ExposureSlice])
async def get_exposure(
    dim: str = "asset_class",
    account_id: Optional[UUID] = None,
    user=Depends(get_current_user),
):
    if dim not in ("asset_class", "sector", "region", "country"):
        raise HTTPException(400, "dim must be one of: asset_class, sector, region, country")
    db = get_admin_db()
    try:
        snapshots.ensure_today_snapshot(
            db, user_id=str(user.id), plaid_client_factory=_build_plaid_client,
        )
    except Exception:
        logger.exception("Lazy Plaid sync failed; continuing with stale data")
    if account_id is not None:
        _assert_owns_account(db, str(user.id), str(account_id))

    if account_id is None:
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", str(user.id))
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]
    else:
        account_ids = [str(account_id)]

    holdings: list[dict] = []
    for aid in account_ids:
        snap = snapshots.get_latest_snapshot(db, account_id=aid)
        if snap:
            holdings.extend(snap["holdings"])

    if not holdings:
        return []

    tickers = list({h["ticker"] for h in holdings})
    # Lazy backfill: pull fresh fundamentals for any ticker that was seeded
    # without complete Yahoo Finance metadata. Capped per call to keep this
    # request snappy; remaining tickers finish on subsequent loads.
    ref_module.ensure_enriched(db, tickers)
    ref_rows = db.table("security_reference").select("*").in_("ticker", tickers).execute().data
    refs = {r["ticker"]: r for r in ref_rows}

    return [
        schemas.ExposureSlice(**slice_) for slice_ in
        exposure_engine.compute_exposure(holdings, refs, dimension=dim)
    ]


@router.get("/lookthrough", response_model=List[schemas.LookThroughHolding])
async def get_lookthrough(
    limit: int = 10,
    account_id: Optional[UUID] = None,
    user=Depends(get_current_user),
):
    """Top-N underlying equities after flattening ETF / mutual-fund look-through.

    For each holding: if security_reference has a `look_through` payload, the
    holding's market value is distributed across underlying tickers by their
    weights, with the residual (uncovered weight) attributed to the parent.
    Cash and bond positions are filtered out so the list focuses on equity
    concentration. Returns the top `limit` rows by aggregated market value.
    """
    if limit <= 0 or limit > 50:
        raise HTTPException(400, "limit must be between 1 and 50")
    db = get_admin_db()
    if account_id is not None:
        _assert_owns_account(db, str(user.id), str(account_id))
        account_ids = [str(account_id)]
    else:
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", str(user.id))
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]

    holdings: list[dict] = []
    total_mv = 0.0
    for aid in account_ids:
        snap = snapshots.get_latest_snapshot(db, account_id=aid)
        if not snap:
            continue
        for h in snap["holdings"]:
            holdings.append(h)
            total_mv += float(h["market_value"])
    if not holdings or total_mv <= 0:
        return []

    tickers = sorted({h["ticker"] for h in holdings})
    ref_module.ensure_enriched(db, tickers)
    ref_rows = db.table("security_reference").select("*").in_("ticker", tickers).execute().data
    refs = {r["ticker"]: r for r in ref_rows}

    # Collect look-through children too — their classification matters for the
    # cash/bond filter below, even though we don't recursively flatten further.
    child_tickers = sorted({
        item["ticker"]
        for r in ref_rows if r.get("look_through")
        for item in r["look_through"]
    } - set(tickers))
    if child_tickers:
        child_rows = (
            db.table("security_reference").select("*")
            .in_("ticker", child_tickers).execute().data
        )
        for r in child_rows:
            refs.setdefault(r["ticker"], r)

    def _is_equity(t: str) -> bool:
        ref = refs.get(t)
        if not ref:
            # Unknown ref — be permissive; the user wants to see concentrations
            # and excluding everything we can't classify hides too much.
            return True
        ac = (ref.get("asset_class") or "").lower()
        return ac in ("equity", "")

    aggregated: dict[str, dict] = {}
    for h in holdings:
        parent = h["ticker"]
        mv = float(h["market_value"])
        ref = refs.get(parent)
        children = ref.get("look_through") if ref else None

        if not children:
            if not _is_equity(parent):
                continue
            slot = aggregated.setdefault(parent, {"market_value": 0.0, "via": set()})
            slot["market_value"] += mv
            continue

        weight_sum = 0.0
        for item in children:
            child = item["ticker"]
            weight = float(item["weight"])
            weight_sum += weight
            if not _is_equity(child):
                continue
            slot = aggregated.setdefault(child, {"market_value": 0.0, "via": set()})
            slot["market_value"] += mv * weight
            slot["via"].add(parent)
        residual = max(0.0, 1.0 - weight_sum)
        if residual > 0 and _is_equity(parent):
            slot = aggregated.setdefault(parent, {"market_value": 0.0, "via": set()})
            slot["market_value"] += mv * residual

    grand = sum(v["market_value"] for v in aggregated.values()) or 1.0
    sorted_rows = sorted(aggregated.items(), key=lambda kv: kv[1]["market_value"], reverse=True)
    out: list[schemas.LookThroughHolding] = []
    for ticker, v in sorted_rows[:limit]:
        ref = refs.get(ticker) or {}
        out.append(schemas.LookThroughHolding(
            ticker=ticker,
            name=ref.get("name"),
            sector=ref.get("sector"),
            country=ref.get("country"),
            market_value=round(v["market_value"], 2),
            percent=round(v["market_value"] / grand * 100, 4),
            via=sorted(v["via"]),
        ))
    return out


@router.get("/timeseries", response_model=schemas.TimeSeriesResponse)
async def get_timeseries(
    from_date: date,
    to_date: date,
    account_id: Optional[UUID] = None,
    overlays: str = "",  # comma-separated subset of: 10y, cpi, spy
    user=Depends(get_current_user),
):
    if from_date > to_date:
        raise HTTPException(400, "from_date must be <= to_date")
    db = get_admin_db()
    try:
        snapshots.ensure_today_snapshot(
            db, user_id=str(user.id), plaid_client_factory=_build_plaid_client,
        )
    except Exception:
        logger.exception("Lazy Plaid sync failed; continuing with stale data")
    if account_id is not None:
        _assert_owns_account(db, str(user.id), str(account_id))

    if account_id is None:
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", str(user.id))
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]
    else:
        account_ids = [str(account_id)]

    if not account_ids:
        return schemas.TimeSeriesResponse(series=[], overlays=[])

    snaps = snapshots.get_snapshots_in_window(db, account_ids, from_date, to_date)
    if not snaps:
        return schemas.TimeSeriesResponse(series=[], overlays=[])

    # Collect every ticker that appears in any snapshot in window.
    all_tickers: set[str] = set()
    for s in snaps:
        for h in s["holdings"]:
            all_tickers.add(h["ticker"])

    prices, unpriced_tickers = ref_module.get_prices_with_misses(
        db, list(all_tickers), from_date, to_date,
    )

    # Per-account series, then sum.
    by_date: dict[date, float] = {}
    for aid in account_ids:
        acct_snaps = [s for s in snaps if s["account_id"] == aid]
        series = reval_engine.timeseries(acct_snaps, prices, from_date, to_date)
        for pt in series:
            by_date[pt["date"]] = by_date.get(pt["date"], 0.0) + pt["total_value"]

    series_points = [
        schemas.TimeSeriesPoint(date=d, total_value=v)
        for d, v in sorted(by_date.items())
    ]

    overlay_set = {o.strip().lower() for o in overlays.split(",") if o.strip()}
    overlay_points: list[schemas.MacroOverlayPoint] = []
    if overlay_set:
        ten_y = fetch_fred_series("DGS10", from_date, to_date) if "10y" in overlay_set else {}
        cpi = fetch_fred_series("CPIAUCSL", from_date, to_date) if "cpi" in overlay_set else {}
        spy_prices: dict[date, float] = {}
        if "spy" in overlay_set:
            raw = ref_module.get_prices(db, ["SPY"], from_date, to_date)
            spy_prices = {d: p for (t, d), p in raw.items() if t == "SPY"}

        all_overlay_dates = set(ten_y) | set(cpi) | set(spy_prices)
        for d in sorted(all_overlay_dates):
            overlay_points.append(schemas.MacroOverlayPoint(
                date=d,
                ten_year_yield=ten_y.get(d),
                cpi_yoy=cpi.get(d),
                spy_close=spy_prices.get(d),
            ))

    snapshot_dates = sorted({
        s["snapshot_date"] if isinstance(s["snapshot_date"], date)
        else date.fromisoformat(s["snapshot_date"])
        for s in snaps
    })

    return schemas.TimeSeriesResponse(
        series=series_points, overlays=overlay_points,
        unpriced_tickers=unpriced_tickers, snapshot_dates=snapshot_dates,
    )


@router.get("/attribution", response_model=schemas.AttributionResult)
async def get_attribution(
    from_date: date,
    to_date: date,
    account_id: Optional[UUID] = None,
    user=Depends(get_current_user),
):
    if from_date >= to_date:
        raise HTTPException(400, "from_date must be < to_date")
    db = get_admin_db()
    if account_id is not None:
        _assert_owns_account(db, str(user.id), str(account_id))

    if account_id is None:
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", str(user.id))
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]
    else:
        account_ids = [str(account_id)]

    if not account_ids:
        return schemas.AttributionResult(
            from_date=from_date, to_date=to_date,
            start_value=0, end_value=0,
            contributions=0, withdrawals=0, dividends=0,
            trades=0, trades_has_basis=True, market=0, unattributed=0,
        )

    # Snapshots in window — use Plan 1's helpers.
    snaps = snapshots.get_snapshots_in_window(db, account_ids, from_date, to_date)
    if not snaps:
        return schemas.AttributionResult(
            from_date=from_date, to_date=to_date,
            start_value=0, end_value=0,
            contributions=0, withdrawals=0, dividends=0,
            trades=0, trades_has_basis=True, market=0, unattributed=0,
        )

    # Compute start_value and end_value via reval engine.
    all_tickers = {h["ticker"] for s in snaps for h in s["holdings"]}
    prices = ref_module.get_prices(db, list(all_tickers), from_date, to_date)
    start_total = 0.0
    end_total = 0.0
    for aid in account_ids:
        acct_snaps = [s for s in snaps if s["account_id"] == aid]
        series = reval_engine.timeseries(acct_snaps, prices, from_date, to_date)
        if series:
            start_total += series[0]["total_value"]
            end_total += series[-1]["total_value"]

    # Investment transactions in window.
    txns = (
        db.table("investment_transactions").select("*")
        .eq("user_id", str(user.id))
        .gte("date", from_date.isoformat())
        .lte("date", to_date.isoformat())
        .order("date")
        .execute().data
    )
    if account_id is not None:
        txns = [t for t in txns if t["account_id"] == str(account_id)]

    result = compute_attribution(
        start_value=start_total, end_value=end_total, transactions=txns,
    )

    # Macro context (best-effort; FRED failures degrade to None).
    ten_y = fetch_fred_series("DGS10", from_date, to_date)
    cpi = fetch_fred_series("CPIAUCSL", from_date, to_date)
    macro = schemas.MacroContext(
        ten_year_yield_change_bps=_yield_change_bps(ten_y, from_date, to_date),
        cpi_yoy_at_end=_latest_value(cpi, to_date),
        spy_period_return_pct=_spy_return_pct(db, from_date, to_date),
    )

    return schemas.AttributionResult(
        from_date=from_date, to_date=to_date, **result, macro_context=macro,
    )


def _yield_change_bps(series: dict, from_d: date, to_d: date) -> Optional[float]:
    start = _latest_value(series, from_d)
    end = _latest_value(series, to_d)
    if start is None or end is None:
        return None
    return round((end - start) * 100, 1)


def _latest_value(series: dict, on: date) -> Optional[float]:
    candidates = [d for d in series.keys() if d <= on]
    return series[max(candidates)] if candidates else None


def _spy_return_pct(db, from_d: date, to_d: date) -> Optional[float]:
    prices = ref_module.get_prices(db, ["SPY"], from_d, to_d)
    spy_dates = sorted(d for (t, d) in prices.keys() if t == "SPY")
    if len(spy_dates) < 2:
        return None
    start = prices[("SPY", spy_dates[0])]
    end = prices[("SPY", spy_dates[-1])]
    if start <= 0:
        return None
    return round((end - start) / start * 100, 2)


@router.get("/summary", response_model=schemas.PortfolioSummary)
async def get_summary(
    window: str = "3M",
    account_id: Optional[UUID] = None,
    user=Depends(get_current_user),
):
    today = date.today()
    deltas = {"1M": 30, "3M": 90, "6M": 180, "YTD": (today - date(today.year, 1, 1)).days,
              "1Y": 365, "All": 365 * 10}
    days = deltas.get(window, 90)
    from_d = today - timedelta(days=days)
    db = get_admin_db()
    # ensure_today_snapshot is NOT called here directly: the nested get_timeseries
    # and get_holdings awaits each trigger it once.  Calling it a third time here
    # would be redundant (three round-trips to the freshness-check query).
    if account_id is not None:
        _assert_owns_account(db, str(user.id), str(account_id))

    ts_response = await get_timeseries(from_date=from_d, to_date=today, account_id=account_id, user=user)
    series = ts_response.series
    holdings = await get_holdings(account_id=account_id, user=user)

    total = series[-1].total_value if series else (sum(h.market_value for h in holdings) if holdings else 0.0)
    start = series[0].total_value if series else total
    period_change = total - start
    pct = (period_change / start * 100) if start else 0.0
    top = sorted(holdings, key=lambda h: h.market_value, reverse=True)[:5]
    return schemas.PortfolioSummary(
        total_value=total,
        period_change=period_change,
        period_change_pct=round(pct, 2),
        top_holdings=top,
        as_of=today,
    )


class StatementTextPreviewRequest(BaseModel):
    text: str


@router.post("/import/statement", response_model=schemas.StatementPreview)
async def import_statement_preview_text(
    body: StatementTextPreviewRequest,
    user=Depends(get_current_user),
):
    if not body.text.strip():
        raise HTTPException(400, "text is required")
    parsed = parse_investment_statement(body.text)
    return _coerce_statement_preview(parsed)


@router.post("/import/statement/file", response_model=schemas.StatementPreview)
async def import_statement_preview_file(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    name = (file.filename or "").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in _STATEMENT_EXTENSIONS:
        raise HTTPException(400, f"unsupported file type {ext or '(none)'}")
    body_bytes = await file.read()
    if len(body_bytes) > _STATEMENT_MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"file exceeds {_STATEMENT_MAX_MB} MB limit")
    if ext == ".pdf":
        text = extract_pdf_text(body_bytes)
    elif ext == ".csv":
        text = extract_csv_text(body_bytes)
    else:
        text = body_bytes.decode("utf-8", errors="replace")
    parsed = parse_investment_statement(text)
    return _coerce_statement_preview(parsed)


def _coerce_statement_preview(parsed: dict) -> schemas.StatementPreview:
    """Normalize parser dict → Pydantic model, handling missing/null statement_date."""
    sd = parsed.get("statement_date") or date.today().isoformat()
    return schemas.StatementPreview(
        statement_date=sd,
        cash_value=parsed.get("cash_value") or 0,
        account_hint=parsed.get("account_hint"),
        total_value_reported=parsed.get("total_value_reported"),
        holdings=[schemas.StatementHolding(**h) for h in parsed.get("holdings", [])],
        investment_transactions=[
            schemas.StatementInvestmentTxn(**t) for t in parsed.get("investment_transactions", [])
        ],
    )


@router.post("/import/statement/confirm", response_model=schemas.SnapshotOut)
async def import_statement_confirm(
    body: schemas.StatementImportConfirm,
    user=Depends(get_current_user),
):
    db = get_admin_db()
    _assert_owns_account(
        db, str(user.id), str(body.account_id),
        expected_types=["brokerage", "retirement"],
    )
    row = snapshots.create_statement_snapshot(
        db,
        user_id=str(user.id),
        account_id=str(body.account_id),
        snapshot_date=body.statement_date,
        cash_value=body.cash_value,
        holdings=[h.model_dump() for h in body.holdings],
        investment_transactions=[t.model_dump() for t in body.investment_transactions],
    )
    return _to_snapshot_out(row)
