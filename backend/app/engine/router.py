from app.provider_credentials.scope import gemini_client
import asyncio
from datetime import date
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from google import genai
from pydantic import BaseModel

from app.config import settings

from app.auth.middleware import get_current_user
from app.db import get_admin_db as _db
from app.engine.cashflow import compute_historical_cashflow, project_cashflow
from app.engine.category_baseline import (
    aggregate_by_category_month,
    compute_baselines,
    reconcile_with_profile,
)
from app.engine.category_baseline.baseline import project_baselined_months
from app.engine.monte_carlo import run_monte_carlo
from app.engine.forecast_service import ForecastUpdate, load_forecast
from app.engine.networth_tree import build_networth_tree
from app.engine.recurring.store import load_rules
from app.engine.expense_statistic import compute_expense_statistic
from app.engine.simulation import simulate_decision
from app.engine.snapshot import compute_snapshot

# Transactions whose transfer_status confirms they're inter-account movements
# rather than spending. needs_review/dismissed/null are kept (not yet a transfer).
_TRANSFER_STATUSES_TO_EXCLUDE = ("auto_paired", "user_confirmed_internal", "external")

router = APIRouter(prefix="/engine", tags=["engine"])


@router.get('/forecast')
async def forecast(months: int = Query(default=12, ge=1, le=360), user=Depends(get_current_user)):
    return await asyncio.to_thread(load_forecast, _db(), str(user.id), months=months)


@router.patch('/forecast')
async def update_forecast(body: ForecastUpdate, months: int = Query(default=12, ge=1, le=360), user=Depends(get_current_user)):
    try:
        return await asyncio.to_thread(load_forecast, _db(), str(user.id), months=months, update=body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _gemini_client():
    """Indirection so tests can patch this without touching real env."""
    return gemini_client()


class DecisionRequest(BaseModel):
    description: str
    upfront_cost: float = 0.0
    monthly_delta: float = 0.0
    asset_value: float = 0.0


class MonteCarloRequest(BaseModel):
    initial_portfolio: float
    monthly_contribution: float
    years: int
    target_amount: Optional[float] = None


class CashFlowExplainRequest(BaseModel):
    projection: List[Dict[str, Any]]
    history: List[Dict[str, Any]]
    starting_balance: float
    monthly_income: float
    monthly_expenses: float
    vesting_events: List[Dict[str, Any]] = []
    fixed_recurring: Dict[str, float] = {}


@router.post("/simulate-decision")
async def simulate(body: DecisionRequest, user=Depends(get_current_user)):
    db = _db()
    uid = str(user.id)
    accounts = db.table("accounts").select("*").eq("user_id", uid).eq("is_active", True).execute().data
    goals = db.table("goals").select("*").eq("user_id", uid).eq("is_active", True).execute().data

    from app.engine.kpis import monthly_income_expense_medians
    medians = monthly_income_expense_medians(db, user_id=uid) or (0.0, 0.0)
    monthly_income, monthly_expenses = medians

    return simulate_decision(
        decision=body.model_dump(),
        accounts=accounts,
        goals=goals,
        monthly_income=monthly_income,
        monthly_expenses=monthly_expenses,
    )


@router.get("/snapshot")
async def get_snapshot(user=Depends(get_current_user)):
    accounts = _db().table("accounts").select("*").eq("user_id", str(user.id)).eq("is_active", True).execute().data
    return compute_snapshot(accounts)


@router.get('/growth')
async def get_growth(window: Literal['3M', '6M', '1Y', 'All'] = '3M', user=Depends(get_current_user)):
    from dateutil.relativedelta import relativedelta
    from app.engine.growth import load_growth
    today = date.today()
    months = {'3M': 3, '6M': 6, '1Y': 12}.get(window)
    start = today - relativedelta(months=months) if months else None
    return load_growth(_db(), str(user.id), start, today)


@router.get("/cashflow")
async def get_cashflow(months: int = 12, user=Depends(get_current_user)):
    db = _db()
    uid = str(user.id)
    profile_rows = db.table("profiles").select("*").eq("id", uid).execute().data
    profile = profile_rows[0] if profile_rows else {}
    accounts = db.table("accounts").select("*").eq("user_id", uid).eq("is_active", True).execute().data

    snapshot = compute_snapshot(accounts)

    vesting_events = []
    for acc in accounts:
        if acc.get("type") == "rsu" and acc.get("vesting_schedule"):
            grant_price = acc.get("grant_price") or 0
            for event in acc["vesting_schedule"]:
                vesting_events.append({
                    "date": event["date"],
                    "value": event["shares"] * grant_price,
                })

    transactions = (
        db.table("transactions").select("*").eq("user_id", uid).execute().data
    ) or []
    txn_excluded = {
        t["id"] for t in transactions
        if t.get("transfer_status") in _TRANSFER_STATUSES_TO_EXCLUDE
    }

    try:
        recurring_rules = load_rules(db, user.id)
    except Exception:
        recurring_rules = []

    aggregated = aggregate_by_category_month(
        transactions,
        recurring_rules=recurring_rules,
        excluded_transaction_ids=txn_excluded,
    )

    opted_out = not bool(profile.get("use_category_baselines", True))
    baselines = compute_baselines(aggregated, opted_out=opted_out, today=date.today())

    # Income / expenses come from real-transaction medians now (the dollar-
    # amount rule). reconcile_with_profile still takes stated_monthly_expenses
    # — we feed it the median so it has a concrete cap to baseline against.
    from app.engine.kpis import monthly_income_expense_medians
    medians = monthly_income_expense_medians(db, user_id=uid) or (0.0, 0.0)
    median_income, median_expenses = medians

    residual, warning = reconcile_with_profile(
        baselines, aggregated, stated_monthly_expenses=median_expenses,
    )

    baselined_months = project_baselined_months(
        baselines, months=months, today=date.today(), aggregated=aggregated
    )

    cashflow = project_cashflow(
        liquid_assets=snapshot["liquid_assets"],
        monthly_income=median_income,
        monthly_expenses=residual,
        months=months,
        vesting_events=vesting_events,
        baselined_months=baselined_months,
    )

    return {
        "cashflow": cashflow,
        "category_baselines": [b.model_dump() for b in baselines if b.tier.value != "T1"],
        "expense_budget_warning": warning.model_dump() if warning else None,
        "residual_monthly_expenses": residual,
        "monthly_income": median_income,
        "income_expense_history_available": median_expenses > 0,
    }


@router.post("/monte-carlo")
async def monte_carlo(body: MonteCarloRequest, user=Depends(get_current_user)):
    return run_monte_carlo(**body.model_dump())


@router.get("/networth-tree")
async def networth_tree(user=Depends(get_current_user)):
    db = _db()
    accounts = (
        db.table("accounts").select("*")
        .eq("user_id", str(user.id))
        .eq("is_active", True)
        .execute().data
    ) or []
    return build_networth_tree(accounts)


@router.get("/cashflow-history")
async def get_cashflow_history(months: int = 12, user=Depends(get_current_user)):
    db = _db()
    uid = str(user.id)
    accounts = (
        db.table("accounts").select("*")
        .eq("user_id", uid).eq("is_active", True)
        .execute().data
    ) or []
    transactions_raw = (
        db.table("transactions").select("date,amount,transfer_status")
        .eq("user_id", uid)
        .execute().data
    ) or []
    transactions = [
        t for t in transactions_raw
        if (t.get("transfer_status") or "") not in _TRANSFER_STATUSES_TO_EXCLUDE
    ]
    snapshot = compute_snapshot(accounts)
    return compute_historical_cashflow(
        transactions=transactions,
        ending_balance=snapshot["liquid_assets"],
        months=months,
    )


_CASHFLOW_EXPLAIN_SYSTEM_PROMPT = """You are a financial assistant. Explain in 2-3 short sentences how the user's cash flow projection is built, grounded in the actual numbers below. Mention the starting balance, the monthly net (income minus expenses), any meaningful fixed recurring inflows/outflows, and any upcoming vesting events that move the line. Do not give advice. Do not start with "Your". Do not exceed 70 words."""


@router.post("/cashflow-explain")
async def cashflow_explain(body: CashFlowExplainRequest, user=Depends(get_current_user)):
    payload = body.model_dump()
    history_end = payload['history'][-1]['balance'] if payload['history'] else 0
    projection_end = payload['projection'][-1]['balance'] if payload['projection'] else 0
    user_message = (
        f"Starting balance: ${payload['starting_balance']:,.0f}\n"
        f"Monthly income: ${payload['monthly_income']:,.0f}\n"
        f"Monthly expenses: ${payload['monthly_expenses']:,.0f}\n"
        f"Fixed recurring: inflow ${payload['fixed_recurring'].get('inflow', 0):,.0f} / outflow ${payload['fixed_recurring'].get('outflow', 0):,.0f}\n"
        f"Vesting events: {len(payload['vesting_events'])} upcoming\n"
        f"Past 12 months: ending at ${history_end:,.0f}\n"
        f"Projection: ending at ${projection_end:,.0f}"
    )
    client = _gemini_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            {"role": "user", "parts": [{"text": _CASHFLOW_EXPLAIN_SYSTEM_PROMPT}]},
            {"role": "user", "parts": [{"text": user_message}]},
        ],
    )
    return {"explanation": response.text or ""}


@router.get("/expenses-statistic")
async def expenses_statistic(window_days: int = 90, user=Depends(get_current_user)):
    db = _db()
    transactions = (
        db.table("transactions").select("date,amount,transfer_status")
        .eq("user_id", str(user.id))
        .execute().data
    ) or []
    return compute_expense_statistic(transactions, window_days=window_days)
