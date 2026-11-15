"""
MCP server for suan-pan finance tools.
Run as a subprocess: python -m app.mcp.server
The server reads user_id from every tool call argument (injected by the advisor router).
"""

import asyncio
import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types as mcp_types

from app.db import get_admin_db as _db
from app.engine.forecast_service import load_forecast
from app.mcp.tools import (
    get_transactions,
    get_spending_by_category,
    detect_transfers,
    update_transaction_category,
    compare_spending_periods,
    bulk_recategorize,
    rescan_transfers,
    get_snapshot,
    score_goal,
    simulate_decision_tool,
    monte_carlo_tool,
    project_cashflow_tool,
    list_recurring_rules,
    update_goal,
    delete_goal,
    find_similar_goal,
    find_goal_by_name,
    compute_annuity,
    get_account_balance_history,
    portfolio_get_holdings,
    portfolio_get_exposure,
    portfolio_get_attribution,
)

logger = logging.getLogger(__name__)
server = Server("suan-pan-finance")


@server.list_tools()
async def list_tools() -> list[mcp_types.Tool]:
    return [
        mcp_types.Tool(
            name='get_financial_forecast',
            description=(
                'Read the same saved assumptions and joint cash/wealth forecast shown in Plan. '
                'Includes recurring income/costs, residual spending, life events, memory events, '
                'user overrides, goal funding and fixed-seed Monte Carlo wealth ranges. '
                'Values are nominal future dollars, unlike the legacy real-dollar portfolio calculator. '
                'Use for dashboard forecast explanations and the combined effect of life goals. '
                'No raw transactions are returned. A funding probability is model-conditional, not a guarantee.'
            ),
            inputSchema={'type':'object', 'properties':{'user_id':{'type':'string'},
                         'months':{'type':'integer', 'minimum':1, 'maximum':360, 'default':12}}, 'required':['user_id']},
        ),
        mcp_types.Tool(
            name="get_transactions",
            description=(
                "Query the user's transactions by date range, category, merchant/description text, or amount. "
                "Use when the user asks for specific transactions or spending details. "
                "Use description_pattern for merchant-name lookups (e.g. 'Verizon', 'Starbucks') — category filters alone won't find them. "
                "Examples: 'Show me my transactions last week'; 'Find all transactions over $100 in December'; 'How much did I spend at Starbucks?'. "
                "Results are reverse-chronological; default limit 100."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "date_from": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
                    "date_to": {"type": "string", "description": "End date in YYYY-MM-DD format"},
                    "category": {"type": "string", "description": "Filter by category (case-insensitive, optional)"},
                    "description_pattern": {"type": "string", "description": "Case-insensitive substring to match in transaction description / merchant name (optional)"},
                    "min_amount": {"type": "number", "description": "Minimum absolute amount (optional)"},
                    "max_amount": {"type": "number", "description": "Maximum absolute amount (optional)"},
                    "limit": {"type": "integer", "description": "Max results, default 100"},
                },
                "required": ["user_id", "date_from", "date_to"],
            },
        ),
        mcp_types.Tool(
            name="get_spending_by_category",
            description=(
                "Get total spending broken down by category for a date range. "
                "Use when the user wants a high-level breakdown of where their money is going. "
                "Examples: 'What did I spend the most on last month?'; 'Break down my Q1 spending by category'. "
                "Returns a sorted list from highest to lowest spend."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "date_from": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "End date YYYY-MM-DD"},
                },
                "required": ["user_id", "date_from", "date_to"],
            },
        ),
        mcp_types.Tool(
            name="detect_transfers",
            description=(
                "Identify transactions that are likely account-to-account transfers (Zelle, Venmo, wire, etc.) rather than real expenses. "
                "Use when a category looks unusually high or the user asks whether a line item is a real expense. "
                "Examples: 'Why is my Shopping category so high this month?'; 'Are any of these transactions just transfers between my accounts?'. "
                "Scans up to `limit` transactions (default 500)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "date_from": {"type": "string", "description": "Start date YYYY-MM-DD (optional; defaults to 30 days ago)"},
                    "date_to": {"type": "string", "description": "End date YYYY-MM-DD (optional; defaults to today)"},
                    "limit": {"type": "integer", "description": "Max transactions to scan, default 500"},
                },
                "required": ["user_id"],
            },
        ),
        mcp_types.Tool(
            name="update_transaction_category",
            description=(
                "Change the category of a single transaction. Pass the transaction id returned by get_transactions. "
                "Use when the user wants to fix the category on one specific transaction. Always confirm with the user first. "
                "Examples: 'Recategorize that $45 Whole Foods charge as Food'; 'Move this Uber transaction from Transport to Transfer'. "
                "new_category must be one of the ALLOWED_CATEGORIES."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "transaction_id": {"type": "string", "description": "The transaction id to update"},
                    "new_category": {"type": "string", "description": "The new category name"},
                },
                "required": ["user_id", "transaction_id", "new_category"],
            },
        ),
        mcp_types.Tool(
            name="compare_spending_periods",
            description=(
                "Compare spending by category between two date ranges. "
                "Use when the user asks how their spending changed over time or between two specific windows. "
                "Examples: 'How did my February spending compare to January?'; 'Am I spending more on Food this quarter than last quarter?'. "
                "Returns delta and percent change per category, plus period totals."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "period_a_start": {"type": "string", "description": "Period A start YYYY-MM-DD"},
                    "period_a_end": {"type": "string", "description": "Period A end YYYY-MM-DD"},
                    "period_b_start": {"type": "string", "description": "Period B start YYYY-MM-DD"},
                    "period_b_end": {"type": "string", "description": "Period B end YYYY-MM-DD"},
                },
                "required": ["user_id", "period_a_start", "period_a_end", "period_b_start", "period_b_end"],
            },
        ),
        mcp_types.Tool(
            name="rescan_transfers",
            description="Re-run the inter-account transfer detector over the user's recent transactions. Use this when the user asks to rescan transfers, refresh the review list, or after they mention importing/linking new accounts. Returns counts of auto-paired and needs-review orphans.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "window_days": {"type": "integer", "description": "How many days back to scan, default 30"},
                },
                "required": ["user_id"],
            },
        ),
        mcp_types.Tool(
            name="bulk_recategorize",
            description=(
                "Reclassify all transactions whose description matches a substring pattern. "
                "Use when the user wants to fix many similar transactions at once. "
                "Examples: 'Recategorize all my Starbucks charges as Food'; 'Move every Zelle transfer out of Shopping into Transfer'. "
                "ALWAYS call with dry_run=true first to preview matches, then ask the user to confirm before calling with dry_run=false."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "date_from": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "End date YYYY-MM-DD"},
                    "description_pattern": {"type": "string", "description": "Case-insensitive substring to match in transaction descriptions"},
                    "new_category": {"type": "string", "description": "Category to assign to matched transactions"},
                    "dry_run": {"type": "boolean", "description": "If true (default), preview matches without updating. Set to false only after user confirmation."},
                },
                "required": ["user_id", "date_from", "date_to", "description_pattern", "new_category"],
            },
        ),
        mcp_types.Tool(
            name="get_snapshot",
            description=(
                "Compute the user's current net-worth snapshot — liquid assets, investments, "
                "non-current assets (notional), total liabilities, and net worth. "
                "Use when the user asks 'what's my net worth', 'how much do I have', or wants a full picture. "
                "Cheap; safe to call any time."
            ),
            inputSchema={
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
            },
        ),
        mcp_types.Tool(
            name="score_goal",
            description=(
                "Score one specific goal's feasibility 0-100 given the user's current monthly surplus + progress. "
                "Returns {feasibility_score, status, months_to_goal}. "
                "Use when the user asks 'will I hit my X goal', 'am I on track for Y', or after they update a goal. "
                "Pass the goal_id from the goals list."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "goal_id": {"type": "string", "description": "uuid of the goal to score"},
                },
                "required": ["user_id", "goal_id"],
            },
        ),
        mcp_types.Tool(
            name="simulate_decision",
            description=(
                "Project the impact of a one-time financial decision on every active goal. "
                "Use when the user is weighing a purchase, refi, payoff, or any large cash event. "
                "Examples: 'Should I buy a $35k car', 'What if I prepay $10k on my mortgage'. "
                "Inputs are in dollars (positive amounts)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "description": {"type": "string", "description": "Plain-English label for the decision (e.g., 'Buy a $35k car')"},
                    "upfront_cost": {"type": "number", "description": "One-time cash outflow in dollars (positive). Default 0."},
                    "monthly_delta": {"type": "number", "description": "Change to monthly cashflow — negative for a new recurring expense, positive for a new recurring income. Default 0."},
                    "asset_value": {"type": "number", "description": "Value of any new asset created by the decision. Default 0."},
                },
                "required": ["user_id", "description"],
            },
        ),
        mcp_types.Tool(
            name="monte_carlo",
            description=(
                "Stochastic portfolio projection over `years` (5000 simulations, fixed seed for determinism). "
                "Returns p10/p25/p50/p75/p90 real-dollar outcomes and optional success rate vs. target. "
                "Use when the user asks about long-term retirement, FIRE, or 'will my money last' questions. "
                "Defaults: initial_portfolio = current investments, monthly_contribution = current monthly surplus."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "years": {"type": "integer", "description": "Projection horizon in years"},
                    "monthly_contribution": {"type": "number", "description": "Monthly contribution. Defaults to current monthly surplus."},
                    "initial_portfolio": {"type": "number", "description": "Starting portfolio value. Defaults to current investment_assets."},
                    "target_amount": {"type": "number", "description": "Optional success target — if given, the response includes success_rate vs this amount."},
                    "annual_return_mean": {"type": "number", "description": "Default 0.07. Override for sensitivity analysis."},
                    "annual_return_std": {"type": "number", "description": "Default 0.15."},
                    "inflation_rate": {"type": "number", "description": "Default 0.03."},
                },
                "required": ["user_id", "years"],
            },
        ),
        mcp_types.Tool(
            name="list_recurring_rules",
            description=(
                "List the user's detected recurring rules (subscriptions, bills, predictable income). "
                "Use when the user asks about recurring charges, subscriptions to cancel, monthly bills, "
                "or anything resembling 'what am I paying for every month'. "
                "Examples: 'List my subscriptions over $20/month'; 'What recurring charges do I have?'. "
                "Returns merchant keyword, frequency, monthly-equivalent amount, and confirmation status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "min_monthly_amount": {"type": "number", "description": "Filter to rules whose monthly-equivalent ≥ this amount (optional)"},
                    "frequency": {"type": "string", "description": "Filter by exact frequency: weekly|biweekly|monthly|quarterly|annual (optional)"},
                    "status": {"type": "string", "description": "Filter by status: user_confirmed|auto_applied|pending_review|user_rejected (optional)"},
                },
                "required": ["user_id"],
            },
        ),
        mcp_types.Tool(
            name="update_goal",
            description=(
                "Update an existing goal's target_amount, target_date, or name. "
                "Use this — NOT goal-create — whenever the user says 'change/update/edit/lower/raise/extend/rename' a goal that already exists. "
                "Look up the goal id from the LIVE STATE goals list and pass it. "
                "Only the fields you pass are changed; omit fields you don't want to touch."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "goal_id": {"type": "string", "description": "uuid of the goal to update (or its name; case-insensitive exact match)"},
                    "name": {"type": "string", "description": "New name (optional)"},
                    "target_amount": {"type": "number", "description": "New target amount (optional)"},
                    "target_date": {"type": "string", "description": "New target date YYYY-MM-DD (optional)"},
                },
                "required": ["user_id", "goal_id"],
            },
        ),
        mcp_types.Tool(
            name="delete_goal",
            description=(
                "Soft-delete (deactivate) an existing goal. "
                "Use when the user says 'delete/remove/get rid of' a goal. "
                "Pass the goal id from the LIVE STATE goals list. "
                "Always confirm with the user before calling unless they explicitly said delete."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "goal_id": {"type": "string", "description": "uuid of the goal to delete (or its name; case-insensitive)"},
                },
                "required": ["user_id", "goal_id"],
            },
        ),
        mcp_types.Tool(
            name="find_similar_goal",
            description=(
                "Search the user's existing goals for one whose name resembles a candidate string. "
                "Call this BEFORE proposing a new goal to avoid creating duplicates "
                "(the most common chat-side data corruption). "
                "Returns the closest match with a similarity score 0-1. "
                "If score >= 0.6, treat the candidate as a likely duplicate and ask the user whether to update_goal instead of creating a new one."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "candidate_name": {"type": "string", "description": "The proposed goal name to check against existing goals"},
                },
                "required": ["user_id", "candidate_name"],
            },
        ),
        mcp_types.Tool(
            name="find_goal_by_name",
            description=(
                "Look up a specific goal by name (fuzzy match) across ALL of the user's active goals, "
                "bypassing the context-window cap. "
                "Use this whenever the user references a goal by name and you cannot find it in the LIVE STATE "
                "context block — it may simply be beyond the top-10 limit. "
                "Returns the matching goal with its id, target_amount, target_date, and feasibility_score, "
                "plus a list of all active goal names for reference. "
                "Never tell the user a goal does not exist without calling this tool first."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "name": {"type": "string", "description": "The goal name to search for (partial match OK)"},
                },
                "required": ["user_id", "name"],
            },
        ),
        mcp_types.Tool(
            name="project_cashflow",
            description=(
                "Month-by-month projected cash balance for the next `months` months (default 12). "
                "Combines profile-derived income/expenses, RSU vesting events, and active recurring rules. "
                "Use when the user asks 'will I have enough cash', 'when does my balance dip below X', or for a runway view."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "months": {"type": "integer", "description": "Months to project. Default 12."},
                },
                "required": ["user_id"],
            },
        ),
        mcp_types.Tool(
            name="compute_annuity",
            description=(
                "Deterministic FV-of-ordinary-annuity calculator. "
                "MUST call this tool for any fixed-rate savings/investment projection question — "
                "do NOT compute annuity math inline in your own reasoning. "
                "Three modes controlled by solve_for: "
                "'months' (given pmt + fv + annual_rate → how many months to reach fv), "
                "'fv' (given pmt + months + annual_rate → what future value will accumulate), "
                "'pmt' (given fv + months + annual_rate → what monthly payment is required). "
                "Use this — NOT monte_carlo — when the user specifies a fixed deterministic rate "
                "(e.g. 'at 7% return', 'assuming 6% annually'). "
                "Examples: 'How long to save $50k at $600/month at 7%?'; "
                "'What will $400/mo grow to in 5 years at 6%?'; "
                "'How much do I need to save monthly to hit $100k in 10 years at 7%?'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "solve_for": {
                        "type": "string",
                        "enum": ["months", "fv", "pmt"],
                        "description": "Which value to solve for: 'months', 'fv', or 'pmt'",
                    },
                    "annual_rate": {
                        "type": "number",
                        "description": "Annual return rate as a decimal (e.g. 0.07 for 7%)",
                    },
                    "pmt": {
                        "type": "number",
                        "description": "Monthly payment/contribution in dollars (required when solve_for is 'months' or 'fv')",
                    },
                    "fv": {
                        "type": "number",
                        "description": "Target future value in dollars (required when solve_for is 'months' or 'pmt')",
                    },
                    "months": {
                        "type": "integer",
                        "description": "Number of months (required when solve_for is 'fv' or 'pmt')",
                    },
                },
                "required": ["user_id", "solve_for", "annual_rate"],
            },
        ),
        mcp_types.Tool(
            name="get_account_balance_history",
            description=(
                "Return per-account monthly balance history for the past N months (default 3). "
                "Use when the user asks 'why is my checking lower than last month?', "
                "'how has my savings account changed?', or any question about how a specific "
                "account's balance has evolved over time. The aggregate snapshot only shows "
                "current totals — this tool provides the month-by-month trend per account. "
                "Returns a list of {month, account_name, account_type, balance} rows. "
                "Optionally scope to a single account_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string", "description": "Restrict to a single account (optional)"},
                    "months": {"type": "integer", "description": "How many months of history to return. Default 3."},
                },
                "required": ["user_id"],
            },
        ),
        mcp_types.Tool(
            name="portfolio_get_holdings",
            description=(
                "Get the user's current investment holdings (aggregated across all "
                "brokerage/retirement accounts, or one account if account_id given). "
                "Use when the user asks 'what do I own', 'how much NVDA do I have', "
                "or wants to inspect any specific position. Returns ticker, quantity, "
                "market value, percent of portfolio, cost basis, unrealized gain."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string", "description": "Restrict to a single account; optional"},
                },
                "required": ["user_id"],
            },
        ),
        mcp_types.Tool(
            name="portfolio_get_exposure",
            description=(
                "Get the user's allocation broken down by one of three dimensions: "
                "'asset_class' (equity, fixed_income, cash, crypto, other), 'sector' "
                "(GICS sectors with top-10 ETF look-through), or 'region' (US, Developed, "
                "Emerging, Global). Use when the user asks 'am I overexposed to tech', "
                "'how much is in equities', or any allocation question. Defaults to asset_class."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "dimension": {"type": "string", "enum": ["asset_class", "sector", "region"]},
                    "account_id": {"type": "string"},
                },
                "required": ["user_id"],
            },
        ),
        mcp_types.Tool(
            name="portfolio_get_attribution",
            description=(
                "Decompose a period's portfolio change into named buckets: market, "
                "contributions, withdrawals, dividends, trades, and unattributed. "
                "Use when the user asks 'why did my portfolio move', 'what drove my "
                "returns this quarter', or any explain-the-change question. Returns "
                "the decomposition plus macro context (10Y yield change, CPI YoY, "
                "SPY return for the period) and one-sentence narrative hints per bucket. "
                "Always call this tool; do not estimate attribution from other data."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "from_date": {"type": "string", "description": "Period start, YYYY-MM-DD"},
                    "to_date": {"type": "string", "description": "Period end, YYYY-MM-DD"},
                    "account_id": {"type": "string", "description": "Restrict to one account; optional"},
                },
                "required": ["user_id", "from_date", "to_date"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[mcp_types.TextContent]:
    db = _db()
    user_id = arguments.get("user_id", "")
    if not user_id:
        return [mcp_types.TextContent(type="text", text=json.dumps({"error": "user_id is required"}))]
    REQUIRED_ARGS: dict[str, list[str]] = {
        "get_transactions": ["date_from", "date_to"],
        "get_spending_by_category": ["date_from", "date_to"],
        "detect_transfers": ["date_from", "date_to"],
        "update_transaction_category": ["transaction_id", "new_category"],
        "compare_spending_periods": ["period_a_start", "period_a_end", "period_b_start", "period_b_end"],
        "bulk_recategorize": ["date_from", "date_to", "description_pattern", "new_category"],
        "rescan_transfers": [],
        "get_snapshot": [],
        "score_goal": ["goal_id"],
        "simulate_decision": ["description"],
        "monte_carlo": ["years"],
        "get_financial_forecast": [],
        "project_cashflow": [],
        "list_recurring_rules": [],
        "update_goal": ["goal_id"],
        "delete_goal": ["goal_id"],
        "find_similar_goal": ["candidate_name"],
        "find_goal_by_name": ["name"],
        "compute_annuity": ["solve_for", "annual_rate"],
        "get_account_balance_history": [],
        "portfolio_get_holdings": [],
        "portfolio_get_exposure": [],
        "portfolio_get_attribution": ["from_date", "to_date"],
    }
    ALLOWED_ARGS: dict[str, set[str]] = {
        "get_transactions": {"date_from", "date_to", "category", "description_pattern", "min_amount", "max_amount", "limit"},
        "get_spending_by_category": {"date_from", "date_to"},
        "detect_transfers": {"date_from", "date_to", "limit"},
        "update_transaction_category": {"transaction_id", "new_category"},
        "compare_spending_periods": {"period_a_start", "period_a_end", "period_b_start", "period_b_end"},
        "bulk_recategorize": {"date_from", "date_to", "description_pattern", "new_category", "dry_run"},
        "rescan_transfers": {"window_days"},
        "get_snapshot": set(),
        "score_goal": {"goal_id"},
        "simulate_decision": {"description", "upfront_cost", "monthly_delta", "asset_value"},
        "monte_carlo": {"years", "monthly_contribution", "initial_portfolio", "target_amount",
                        "annual_return_mean", "annual_return_std", "inflation_rate"},
        "get_financial_forecast": {"months"},
        "project_cashflow": {"months"},
        "list_recurring_rules": {"min_monthly_amount", "frequency", "status"},
        "update_goal": {"goal_id", "name", "target_amount", "target_date"},
        "delete_goal": {"goal_id"},
        "find_similar_goal": {"candidate_name"},
        "find_goal_by_name": {"name"},
        "compute_annuity": {"solve_for", "annual_rate", "pmt", "fv", "months"},
        "get_account_balance_history": {"account_id", "months"},
        "portfolio_get_holdings": {"account_id"},
        "portfolio_get_exposure": {"dimension", "account_id"},
        "portfolio_get_attribution": {"from_date", "to_date", "account_id"},
    }
    args = {k: v for k, v in arguments.items() if k != "user_id" and k in ALLOWED_ARGS.get(name, set())}
    missing = [k for k in REQUIRED_ARGS.get(name, []) if k not in args]
    if missing:
        return [mcp_types.TextContent(type="text", text=json.dumps({"error": f"Missing required args: {missing}"}))]

    try:
        if name == "get_transactions":
            result = get_transactions(db, user_id, **args)
        elif name == "get_spending_by_category":
            result = get_spending_by_category(db, user_id, **args)
        elif name == "detect_transfers":
            result = detect_transfers(db, user_id, **args)
        elif name == "update_transaction_category":
            result = update_transaction_category(db, user_id, **args)
        elif name == "compare_spending_periods":
            result = compare_spending_periods(db, user_id, **args)
        elif name == "bulk_recategorize":
            result = bulk_recategorize(db, user_id, **args)
        elif name == "rescan_transfers":
            result = rescan_transfers(db, user_id, **args)
        elif name == "get_snapshot":
            result = get_snapshot(db, user_id, **args)
        elif name == "score_goal":
            result = score_goal(db, user_id, **args)
        elif name == "simulate_decision":
            result = simulate_decision_tool(db, user_id, **args)
        elif name == 'get_financial_forecast':
            result = await asyncio.to_thread(load_forecast, db, user_id, **args)
        elif name == "monte_carlo":
            result = monte_carlo_tool(db, user_id, **args)
        elif name == "project_cashflow":
            result = project_cashflow_tool(db, user_id, **args)
        elif name == "list_recurring_rules":
            result = list_recurring_rules(db, user_id, **args)
        elif name == "update_goal":
            result = update_goal(db, user_id, **args)
        elif name == "delete_goal":
            result = delete_goal(db, user_id, **args)
        elif name == "find_similar_goal":
            result = find_similar_goal(db, user_id, **args)
        elif name == "find_goal_by_name":
            result = find_goal_by_name(db, user_id, **args)
        elif name == "compute_annuity":
            result = compute_annuity(**args)
        elif name == "get_account_balance_history":
            result = get_account_balance_history(db, user_id, **args)
        elif name == "portfolio_get_holdings":
            result = portfolio_get_holdings(db, user_id, **args)
        elif name == "portfolio_get_exposure":
            result = portfolio_get_exposure(db, user_id, **args)
        elif name == "portfolio_get_attribution":
            result = portfolio_get_attribution(db, user_id, **args)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        logger.exception("Tool %s failed", name)
        result = {"error": str(e)}

    return [mcp_types.TextContent(type="text", text=json.dumps(result))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
