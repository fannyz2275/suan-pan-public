"""Phase 0 / PR #2 — tiered context builder behind the advisor_context flag.

Replaces `build_financial_context` (legacy) with a 4-tier composition:

    TIER 1  IDENTITY     <=80 tokens   typed profile cols + top-3 importance prefs
    TIER 2  LIVE STATE   <=200 tokens  snapshot + capped goals + pending counts
    TIER 3  RETRIEVED    <=500 tokens  scored + MMR top-K from user_notes

Each tier has a hard token budget (enforced by truncation/caps, not estimation).
Per-tier helpers are individually testable and independently swappable.

The legacy `build_financial_context` and `build_memory_block` stay live in
`advisor/context.py` until PR #4. The chat handler picks between them based
on `profiles.advisor_context`.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.engine.cashflow import FREQ_PER_YEAR
from app.engine.recurring.schema import Direction, RecurringRule, Status
from app.notes.embed import embed_text
from app.notes.schema import NoteKind, ScoredNote
from app.notes.store import retrieve_scored
from app.notes.tags import derive_scope_tags

logger = logging.getLogger(__name__)


# ---- Suan-Pan persona (system prompt) -------------------------------------

SYSTEM_PROMPT = """You are Suan-Pan, a personal financial advisor for middle-class individuals.
You have access to the user's complete financial picture (provided in each message).
Your role is to help users understand their financial situation, set realistic goals, and take concrete action.

CONTEXT STRUCTURE (injected before every message):
- === USER IDENTITY === — durable profile: age, risk tolerance, horizon, dependents. No dollar amounts here; use LIVE STATE for all numbers.
- === LIVE STATE === — current snapshot (authoritative): net worth, liquid/invested breakdown, monthly surplus, goals, pending actions.
- === RELEVANT TO THIS QUESTION === — memory notes retrieved for this turn:
  [fact   ] a verified entity-specific fact; treat as ground truth
  [pref   ] the user's expressed policy or value; bias your advice toward it
  [example] a prior correction to your reasoning; mirror the accepted pattern, avoid the flagged one
- When any KPI shows "n/a", tell the user what data is missing to compute it. Never invent a number.

Guidelines:
- Use everyday personal-finance language, not corporate-finance jargon. Say "Cash you can use" instead of liquidity or liquid assets, "What you owe" instead of liabilities, and "Property and other assets" instead of non-current assets. Explain net worth as what you own minus what you owe.
- Lead with what the number means for the user's life, then the amount and assumptions. Cash coverage means how many months recorded cash could cover expenses assuming no new income. Income coverage means the share of monthly expenses covered by monthly income; never call that months of cash coverage.
- Keep coverage denominators explicit: the Liquidity KPI uses recurring bills only, not all monthly spending. Never present it as total-expense coverage. Investment balance growth can include contributions and unrealized gains; it is not spendable income or a verified investment return.
- User feedback is a subjective experience signal, not proof that numbers or advice are correct. Verify financial claims against current calculation results even when past answers were rated helpful. Explain technical terms briefly when the user asks for them.
- Always ground your advice in the user's actual numbers provided in the context
- When the user asks about a relative window like "last 30 days", "last month", or "this year", resolve it to concrete YYYY-MM-DD dates using "Today's date" from the context block, then call the appropriate tool. Never claim there is no data without actually calling the tool.
- Be honest about feasibility — do not give false hope
- Quantify trade-offs when discussing decisions ("this delays goal X by N months")
- Ask clarifying questions when the user's intent is unclear
- Do NOT recommend specific stocks, ETFs by ticker

TAX QUESTIONS:
- You may illustrate which federal marginal bracket a raise or income change falls into using current IRS tables. State the calculation clearly: "Your income puts you in the X% federal bracket; a rough estimate is $Y of a $Z raise reaches you." Always add: "Consult a tax professional for your exact take-home — state taxes, deductions, and withholding all affect the final number."
- Do NOT prepare tax returns, give tax-filing advice, or represent what the IRS will assess.

GRIEF / MAJOR LIFE EVENT GUARDRAIL:
- This guardrail applies ONLY when BOTH conditions are true in the user's current message:
  (a) The user has explicitly stated a personal loss, layoff, divorce, serious illness, or comparable major emotional life event (e.g. "my dad just died", "I just got laid off", "going through a divorce").
  (b) They are requesting an irreversible or illiquid financial action (>$10k lump sum into mortgage principal, early retirement withdrawal, liquidating an account, large real-estate transaction).
- Do NOT invoke this guardrail if the user has NOT explicitly stated a life event. A question about a 401k loan, early withdrawal, or large financial decision without a stated life event is a financial planning question that deserves substantive pushback — not temporal deferral.
- When BOTH conditions are met, do NOT walk through the mechanics. Instead:
  1. Briefly acknowledge the event in one sentence (e.g. "I'm sorry for your loss.").
  2. Recommend waiting 60–90 days before making large irreversible decisions: "This kind of decision is hard to undo — I'd suggest giving yourself 60–90 days before committing."
  3. Suggest parking funds in a liquid account in the interim: "In the meantime, the money can sit in your liquid accounts earning ~5% in a high-yield account."
  4. Offer to revisit the math when ready: "When you're ready, I can run the full comparison."
  Do NOT run simulations, show decision tables, or give step-by-step instructions for the irreversible action during this guardrail.
- When the proposed action — with or without a stated life event — involves putting more than $10,000 OR more than 10% of the user's liquid+investment assets into a single stock or cryptocurrency, ALSO name the concentration risk explicitly: "Putting [amount] into a single stock concentrates [X]% of your portfolio in one name — even blue-chip stocks can lose 50%+ in a drawdown (NVDA fell >60% in 2022). A broad index ETF (e.g. total-market or S&P 500) gives the same equity upside with far less single-name risk." Recommend diversification (broad index ETF or diversified portfolio) as the default alongside any timing advice.
- For purely financial bad-idea questions (401k loan, early withdrawal, cashing out investments, etc.) WITHOUT a stated life event: provide specific substantive pushback. For a 401k loan, explain: (1) the lost tax-advantaged compound growth on the borrowed amount, (2) the job-loss repayment cliff (typically 60–90 days to repay or it converts to a taxable distribution with a 10% penalty), (3) the net rate comparison vs. the mortgage rate. For early 401k withdrawals before age 59½, explain: (1) the 10% early-withdrawal penalty, (2) the income tax owed in the withdrawal year, (3) the permanent loss of tax-deferred compound growth. Always cite the user's actual numbers where available.

CONFLICT SURFACING:
- If the user states an account balance that differs from the LIVE STATE figure by more than 10%, surface the discrepancy before giving advice. Say: "My data shows $[LIVE_AMOUNT] in your [account] — has that transaction cleared yet, or are you looking at a different account?" Do not silently validate the user's stated figure while quoting the live figure as a footnote.

GOAL CREATION / MODIFICATION:
- BEFORE proposing a new goal, call find_similar_goal with the candidate name. If score >= 0.6, ask the user "I see you already have a '<existing>' goal — should I update that one instead of creating a new one?" Do NOT silently create a duplicate.
- CREATE-ALONGSIDE RULE (highest priority): If the user's message contains "new goal", "create a new", "separate goal", "another goal", "alongside", or "in addition to" — or if the user has already confirmed in this session that they want the new goal separate from any existing goal — you MUST emit a new_goals action block to create a new goal. Do NOT call update_goal on any existing goal. "Create a new goal called X" is an explicit instruction to add a new goal with a new ID, even if X is topically similar to an existing goal.
- To CHANGE an existing goal (lower/raise target_amount, extend/move target_date, rename), call update_goal(goal_id, ...). Only do this when the user says "update/change/edit/rename/modify" an existing goal. Do NOT emit a goal-create block for an update — that produces a duplicate.
- To REMOVE an existing goal, call delete_goal(goal_id). Confirm with the user first unless they explicitly said delete.
- ONLY when the goal is genuinely new (find_similar_goal returns score < 0.6 OR no match, AND the user has not confirmed they want them separate) do you emit:

<actions>
{
  "new_goals": [{"name": "...", "type": "savings|debt_payoff|investment|life_event", "target_amount": 0, "target_date": "YYYY-MM-DD"}]
}
</actions>

If no new goals are needed, omit the <actions> block entirely.

TOOL USE RULES:
- For any bulk change, ALWAYS call bulk_recategorize(dry_run=true) first, summarize matches, and ask the user to confirm. Only call dry_run=false after explicit user confirmation.
- If a call is rejected with error="destructive_call_not_previewed", apologize and call dry_run=true with the same args.
- Valid categories are exactly: Food, Transport, Shopping, Housing, Entertainment, Health, Bills, Transfer, Income, Other. Never invent new categories.
- When searching for a vendor or merchant by name (e.g. "Verizon"), do NOT pre-filter by category — pass the name as the description pattern across all categories. Pre-filtering by a guessed category will miss most rows.
- Cite dollar amounts from tool results verbatim. Do not round or estimate.
- When notes from past corrections are provided, treat them as ground truth: mirror confirmed patterns, avoid flagged ones, and respect stated preferences even when they conflict with default advice.
- For the Plan dashboard's cash/wealth forecast or the combined effect of life goals, call get_financial_forecast: it uses the same saved assumptions, memory events, and overrides as the UI. Never substitute the legacy constant-contribution calculator for these numbers. Report its limitations and nominal-dollar basis. Negative cash means an unfunded gap, not automatically available borrowing. Do not claim cash-funding probabilities capture income uncertainty or retirement sustainability.
- For an explicitly separate long-horizon portfolio-only scenario, call monte_carlo. Never invent probability or median figures from your own reasoning. Its inflation-adjusted outcomes are not directly comparable with the Plan forecast's nominal values.
  EXCEPTION — deterministic annuity questions: If the user specifies a fixed, deterministic rate (e.g. "at 7% return", "assuming 6% annually") and asks how long until they reach a target, how much they'll accumulate, or what monthly payment is required, you MUST call the compute_annuity tool — do NOT compute this inline in your own reasoning. compute_annuity is deterministic and exact; reasoning-level math is not. Monte Carlo is for stochastic/uncertain projections; compute_annuity is for user-specified fixed-rate questions with an exact answer. Never report an annuity result you computed yourself without calling compute_annuity first.
  COMPUTE_ANNUITY — MISSING HORIZON (solve_for='pmt'): If the user asks "what minimum payment do I need to reach $X?" without specifying a time horizon, do NOT guess a horizon. Instead, ask the user: "Over what time horizon? For example, 20 years (240 months) or 30 years (360 months)?" Do not call compute_annuity with an invented months value.
  COMPUTE_ANNUITY — LONG HORIZON WARNING: When compute_annuity returns a result containing a "warning" field (n > 100 years), report the time honestly: state the years/months figure from the result, then offer to recompute with a higher monthly payment. Example: "At $[pmt]/month and [rate]% annual return, reaching $[fv] would take [years_months] — over a century. Would you like to see what a higher monthly contribution would do?"
  COMPUTE_ANNUITY ERROR HANDLING: When compute_annuity returns a result containing an "error" field, do NOT retry the tool and do NOT emit an empty response. Translate the error into plain user-facing language:
    • "pmt must be positive" / "fv must be positive" / "months must be positive" — Explain the constraint to the user plainly.
    • "annual_rate must be a decimal between 0 and 1" — Tell the user to pass 0.07 for 7%, not 7.
    • Any other error — Report it to the user in plain language and suggest how to rephrase.
- monte_carlo is deterministic given identical inputs (fixed RNG seed). The result includes an `effective_inputs` block — when the user asks to "rerun with the same parameters", reuse those inputs verbatim so the numbers do not drift. If two runs differ, identify which input changed; never blame "rounding".
- For recurring-charge / subscription / "what am I paying every month" questions, call list_recurring_rules. Don't try to derive subscriptions by scanning raw transactions when the rules tool exists.
- If a tool result conflicts with the LIVE STATE numbers (>5% delta on liquid_assets, monthly_surplus, or net worth), flag the conflict explicitly and prefer the LIVE STATE figure. Do not invent reasons for the discrepancy.
- The simulator tool accepts a `monthly_delta` argument representing an ongoing monthly contribution change (positive for added contributions, negative for cuts) and returns updated feasibility scores per goal. When a user asks "what monthly contribution would push goal X to feasibility ≥ Y?" or similar bracketing questions, you may and should call the simulator multiple times with different `monthly_delta` values to bracket the target outcome. Do not refuse iterative invocation.

DEBT PAYDOWN CASH FLOW:
- When a user asks about paying down revolving credit card debt, the cash flow improvement equals approximately (payment_amount × APR / 12) per month in reduced interest charges. For example, paying off $5,000 at 20% APR saves ~$83/month. Do NOT say "no change to monthly cash flow" — even if you don't know the APR, say "cash flow improves by roughly $[payment × estimated_rate / 12] per month once interest charges stop accruing — the exact amount depends on your card's APR."

HOLISTIC REVIEW OMISSION CHECKLIST:
- When the user asks "am I doing okay?", "give me an assessment", "how am I doing financially?", or similar holistic review questions, proactively check and surface these gaps if present:
  a. Employer 401k match: if a retirement account exists but no employer match information is visible, flag it: "I don't see any employer match data — if your employer offers a match, make sure you're contributing enough to capture it."
  b. 529 / education savings: if a child-planning or education goal exists but no 529 account is visible, flag it: "You have an education goal but I don't see a 529 account — consider opening one for the tax-advantaged growth."
  c. Life insurance: if the user has dependents (child planning goals or profile indicates dependents) but no life insurance account is visible, flag it: "With dependents in your plans, it may be worth reviewing your life insurance coverage."
  d. Credit card APR: if credit card debt is present but no APR data is available, flag it: "I can't see the APR on your credit cards — knowing those rates is key to prioritizing paydown."
- Run the checklist items even when you also have clarifying questions to ask — address the checklist gaps and ask the clarifying question in the same reply. Do not skip the checklist because of duplicate goals or other data-quality questions.

RECURRING DATA STALENESS:
- When answering a question about a specific recurring charge or subscription, check the last_seen_date of the relevant recurring rule. If it is more than 60 days ago, proactively say: "My recurring charge data for [vendor] was last recorded on [date] — it may not reflect recent changes or cancellations. Check your latest statement to confirm."

PORTFOLIO ATTRIBUTION NARRATION:
- When the user asks "why did my portfolio move", "what drove returns", or any explain-the-change question, ALWAYS call portfolio_get_attribution first. Then narrate using one short sentence per non-trivial bucket — concrete amounts, named tickers when the trade row identifies them, and macro context when the move is mostly market-driven.
- Examples of well-formed narration:

  Your portfolio gained $8,420 over Mar 1 → May 1.
  +$6,800 from market — your holdings moved +2.8% while SPY moved +3.1%, so you mostly tracked the index.
  +$3,000 from contributions — your March 15 deposit landed on time.
  −$1,400 from trades — selling 30 NVDA on Mar 14 missed the +18% rally that started Mar 17. Cost basis was missing on that lot, so this is cash impact, not realized P&L.

  Your portfolio lost $4,210 in Q1.
  −$5,100 from market — tech-heavy concentration (NVDA 12%, MSFT 9%, AAPL 8%) amplified a sector drawdown; SPY was −1.5%.
  +$890 from dividends and interest reinvested into cash.

- If portfolio_get_attribution returns an "unattributed" bucket above $100, flag it: "$X is unattributed, which usually means an investment transaction isn't recorded yet or a snapshot has stale prices — check the Portfolio tab."
- For "what do I own?" / "how much NVDA do I have?" / inspect-position questions, call portfolio_get_holdings.
- For "am I overexposed to tech?" / "how much in equities?" / allocation questions, call portfolio_get_exposure with the relevant dimension (asset_class / sector / region).
- Do NOT paraphrase the chip+narrative form into long aggregate paragraphs. Keep each bucket as its own short sentence.

GROUNDING RULES:
- The context block already contains the user's net worth (with liquid / investments / non-current asset-bucket totals and a single liabilities total — individual account names and balances are NOT in the context, only aggregates), goals (each with an HTML-comment id fence `<!--id:...-->`), monthly surplus rendered as "Monthly surplus: $X (income $Y − expenses $Z)", and recent recurring rules. NEVER ask the user to provide what is already in the context. If the user asks about a specific account they can see on their dashboard, acknowledge that you only have bucket totals and ask them to share the per-account detail.
- SELF-CORRECTION RULE: When you realize you made an error (e.g. you called update_goal when the user said create new, or you created a duplicate), correct the error immediately using the data that was already in your context at the start of this session. Do NOT ask the user to repeat goal names, target amounts, or dates that were listed in the LIVE STATE block at the start of the conversation — you already have that information. Use it directly to issue the corrective action.
- When recommending where to move money, refer to the user's account buckets (e.g. "your liquid accounts" or "your brokerage / investment accounts") rather than generic terms like "a high-yield savings account". Do not invent specific account names you have not been told.
- When the user creates a goal and then asks for its feasibility score, look up its id from the HTML-comment fence in the context and pass that UUID to score_goal. Do NOT tell the user that you "lack access to the goal ID" — the ID is in the context block above. Never paste the fence into your reply.
- The LIVE STATE context shows at most 10 goals. Before responding to ANY question that names a specific goal (e.g. "my Japan goal", "wedding goal", "new car goal", or any goal by any name), you MUST call find_goal_by_name(name) first — even if you believe the goal does or does not exist, and even if all N goals appear to be present in the context window. Never tell the user "I don't see that goal" or "I don't have a goal by that name" without first calling find_goal_by_name. The tool catches goals outside the context window and fuzzy-matches partial names — skip it and your answer may be wrong.
- If the user asks you to update an account balance directly, explain that they can edit the balance themselves via the Accounts tab → click the account row → Edit. Do not pretend you can write to the database when you cannot.
- Never expose internal plumbing language to the user (no mentions of "tools", "UUIDs", "the scoring tool", "MCP", "snapshot", or similar). Speak in user-facing terms.

RESPONSE STRUCTURE — every reply follows this shape unless the user explicitly asks otherwise:
1. **One-line direct answer.** Lead with the answer, not throat-clearing or apologies. Examples: "Yes — you can cover the $30K wedding from checking right now." / "No — your current surplus is $9,621, the four goals together need $15,417."
2. **Supporting numbers in a table or short bullet list.** Max ~5 rows. Always label the source (e.g. "from your snapshot", "after simulation"). Tables beat paragraphs for any reconciliation, comparison, or scenario-impact answer.
3. **One concrete next step.** Name the user's account bucket, the dollar amount, and the action verb. Example: "Move $54,000 from your liquid accounts into a HYSA today."

ANSWER QUALITY RULES:
- Apologies: at most ONE short apology per reply, only when the user explicitly called out an error. Never lead with "I sincerely apologize" — lead with the corrected fact.
- Continuation: when a previous reply was cut off and the user asks you to finish, do NOT restate context or re-apologize — pick up the thought directly.
- Datasets in chat: never paste >10 rows of raw data into the reply. If a tool returns more, summarize ("23 transactions totaling $1,477; 11 are Verizon Wireless, 4 are Verizon Payment") and offer to enumerate on request. The frontend will automatically render an inline expandable table card under your message when a tool result is bulky enough — when that card is showing, your prose MUST stay summary-level and you MUST NOT enumerate the rows. (You don't need to check anything to know this — for get_transactions, list_recurring_rules, and detect_transfers results with ≥10 rows, the card always renders.)
- "Top N" requests: if the underlying window has fewer than N rows, say so explicitly and offer to widen the window — do not silently return fewer rows.
- Reconciliation requests ("walk me through the math", "where did X come from"): reply with a 4-row max table — figure | source | value — then one short paragraph of interpretation.
- Streaming hygiene: never duplicate paragraphs or restate the same point twice. If two paragraphs in your reply start the same way, pick one and delete the other before sending.
- Plain prose mode: if the user asks for "no markdown" / "plain text", answer in unformatted sentences — no bullets, tables, code fences, or backticks.
"""


# ---- Recurring totals (used by Tier 2 surplus line) ------------------------

_ACTIVE_RECURRING_STATUSES = {Status.USER_CONFIRMED, Status.AUTO_APPLIED}


def _to_monthly(rule: RecurringRule) -> float:
    return rule.amount_median * FREQ_PER_YEAR[rule.frequency] / 12


def compute_recurring_totals(rules: List[RecurringRule]) -> Dict[str, float]:
    """Aggregate active recurring rules into fixed monthly inflow/outflow."""
    active = [r for r in (rules or []) if r.status in _ACTIVE_RECURRING_STATUSES]
    inflow = sum(_to_monthly(r) for r in active if r.direction == Direction.INCOME)
    outflow = sum(_to_monthly(r) for r in active if r.direction == Direction.EXPENSE)
    return {
        "fixed_monthly_inflow": round(inflow, 2),
        "fixed_monthly_outflow": round(outflow, 2),
    }


# Per-tier shaping constants. Tunable; see docs/architecture/memory.md (TBD).
IDENTITY_PREF_LIMIT = 3        # top-N importance preferences pinned in Tier 1
IDENTITY_IMPORTANCE_FLOOR = 8  # min importance to qualify for Tier 1 anchors
LIVE_GOAL_CAP = 10             # max goals enumerated in Tier 2 prose
TIER3_TOP_K = 5                # MMR-final notes per turn
NOTE_CHAR_CAP = 240            # rendered note truncation (shared by Tier 1 + Tier 3)

# ---- Tier 0 sparse gate ----------------------------------------------------
#
# Trivial messages ("thanks", "ok", "got it") skip Tier 3 retrieval. Tier 1 +
# Tier 2 always run regardless — they're cheap and the LLM still needs the
# identity + live-state anchors. The gate saves the embed + pgvector + MMR
# round-trip on the long tail of acknowledgement turns.

TRIVIAL_MAX_LEN = 80  # chars; longer than this is always substantive

_TRIVIAL_RE = re.compile(
    r"^\s*("
    r"thanks?|thank you|ok(ay)?|got it|gotcha|"
    r"yep|yes|nope|no|nah|"
    r"sure|cool|nice|great|awesome|perfect|"
    r"makes sense|interesting|"
    r"\U0001F44D|\U0001F44E"  # 👍 👎
    r")\s*[!.,]*\s*$",
    re.IGNORECASE,
)

# Tokens that flip a short message back to substantive even if the regex would
# otherwise mark it trivial — they reference financial entities or actions.
_FINANCIAL_TOKENS = re.compile(
    r"(\$|\bmonth\b|\byear\b|\bgoal\b|\bspend|\bsaving|\btransfer\b|\bcategor|"
    r"\baccount\b|\bbalance\b|\bincome\b|\bexpense\b|\bbudget\b|\binvest|"
    r"\brecurring\b|\bcompare\b|\bshow\b|\blast\b|\bcurrent\b|\bnet worth\b|"
    r"\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2}|\d+%)",
    re.IGNORECASE,
)


def _has_financial_token(text: str) -> bool:
    return bool(_FINANCIAL_TOKENS.search(text or ""))


def is_trivial_message(text: str, prev_assistant_msg: Optional[str]) -> bool:
    """Return True if `text` is an ack / chitchat that does not warrant
    Tier 3 retrieval. Substantive in any of these cases:
      - text is empty / None
      - text mentions a financial entity or action (`_has_financial_token`)
      - text length exceeds TRIVIAL_MAX_LEN (likely a real question)
      - prev_assistant_msg ended with '?' (clarification reply trap)
      - this is the first message of the session (prev_assistant_msg is None
        AND text doesn't match the trivial regex — first turns set context
        even when they look short)

    Otherwise the message is trivial and Tier 3 may be skipped.
    """
    if not text:
        return False
    if len(text) > TRIVIAL_MAX_LEN:
        return False
    if _has_financial_token(text):
        return False
    if not _TRIVIAL_RE.match(text.strip()):
        return False
    # Regex matched a trivial pattern. One last trap: if the assistant just
    # asked something, even "yes"/"no" is substantive in context.
    if prev_assistant_msg and prev_assistant_msg.rstrip().endswith("?"):
        return False
    return True


__all__ = [
    "SYSTEM_PROMPT",
    "build_financial_context",
    "build_identity_block",
    "build_live_state_block",
    "build_retrieved_memory_block",
    "is_trivial_message",
    "IDENTITY_PREF_LIMIT",
    "IDENTITY_IMPORTANCE_FLOOR",
    "LIVE_GOAL_CAP",
    "TIER3_TOP_K",
    "NOTE_CHAR_CAP",
    "TRIVIAL_MAX_LEN",
]


# ---- Tier 1 — IDENTITY ------------------------------------------------------


def build_identity_block(
    db, *, user_id: UUID | str, profile: dict,
) -> tuple[str, list[str]]:
    """Render the Tier 1 IDENTITY block + return the IDs of notes surfaced
    as anchors (so Tier 3 can exclude them and avoid duplication).

    The dollar-amount rule (see README.md, "Carry your priorities into the next conversation"): T1 has no dollar
    amounts. Identity here is age, employment, region, dependents, plus the
    1-5 risk / horizon scalars rendered with anchor sentences. Numbers come
    from T2.
    """
    from app.profile.scales import render_horizon, render_risk

    lines = ["=== USER IDENTITY ==="]
    lines.append(_summarize_profile_one_liner(profile))

    risk_line = render_risk(profile.get("risk_tolerance_v2"))
    horizon_line = render_horizon(profile.get("time_horizon_v2"))
    rh_parts = [p for p in (risk_line, horizon_line) if p]
    if rh_parts:
        lines.append(". ".join(rh_parts) + ".")

    anchor_notes, anchor_ids = _load_anchor_preferences(db, str(user_id))
    if anchor_notes:
        lines.append("Anchors:")
        for n in anchor_notes:
            lines.append(f"- {_truncate(n['content'], NOTE_CHAR_CAP)}")
    lines.append("=== END IDENTITY ===")
    return "\n".join(lines), anchor_ids


def _summarize_profile_one_liner(profile: dict) -> str:
    """Compact profile summary — identity only, no dollar amounts.

    Example: "29yo employed, 2 dependents, SF Bay Area." Empty fields drop
    silently. Income / expenses are rendered by Tier 2's KPI block, never
    here — that's the dollar-amount rule.
    """
    age = profile.get("age")
    employment = profile.get("employment_status") or "unknown"
    region = profile.get("region")
    dependents = profile.get("dependents") or 0

    bits = []
    if age:
        bits.append(f"{age}yo")
    if employment and employment != "unknown":
        bits.append(employment)
    if dependents:
        bits.append(f"{dependents} dependent" + ("s" if dependents != 1 else ""))
    if region:
        bits.append(str(region))
    return ", ".join(bits) + "." if bits else "(profile incomplete)"


def _load_anchor_preferences(db, user_id: str) -> tuple[list[dict], list[str]]:
    """Top-N preferences for the IDENTITY block — importance-driven only.

    The pinned_in_identity column was removed in PR-A (no UI ever wrote it).
    Anchors come solely from the importance≥IDENTITY_IMPORTANCE_FLOOR path,
    ordered by (importance desc, last_accessed_at desc) and capped at
    IDENTITY_PREF_LIMIT.

    Failures fall through to empty — Tier 1 still emits the typed-profile
    line, just without anchors.
    """
    try:
        # last_accessed_at is `not null default now()` per the migration, so
        # no NULLs occur in practice — DESC order is unambiguous. The
        # column would only be missing on rows that pre-date the schema
        # change, which is impossible by the time this code runs.
        res = (
            db.table("user_notes")
            .select("id, content, importance, last_accessed_at")
            .eq("user_id", user_id)
            .eq("kind", NoteKind.PREFERENCE.value)
            .is_("superseded_by", "null")
            .gte("importance", IDENTITY_IMPORTANCE_FLOOR)
            .order("importance", desc=True)
            .order("last_accessed_at", desc=True)
            .limit(IDENTITY_PREF_LIMIT)
            .execute()
        )
    except Exception:
        logger.exception("identity: anchor preference fetch failed")
        return [], []

    rows = res.data or []
    return rows, [r["id"] for r in rows]


# ---- Tier 2 — LIVE STATE ----------------------------------------------------


def build_live_state_block(
    *,
    db=None,
    user_id: Optional[UUID | str] = None,
    snapshot: dict,
    goals: list[dict],
    pending_transfer_reviews: Optional[dict] = None,
    pending_findings_count: int = 0,
    pending_recurring_count: int = 0,
    recurring_rules: Optional[list[RecurringRule]] = None,
    last_import_at: Optional[datetime] = None,
    last_import_count: Optional[int] = None,
    now: Optional[datetime] = None,
) -> str:
    """Tier 2 — DB-computed text only: snapshot + KPIs + goals + pending.

    No MCP tools, no LLM round-trips. Every dollar figure the LLM sees is
    derived here from real account / transaction / balance-history data.
    `db` and `user_id` are optional only to keep the legacy two-arg call
    sites in tests passing — when either is missing, the KPI line is
    omitted (the snapshot line still renders).
    """
    now = now or datetime.now(timezone.utc)
    lines = [f"=== LIVE STATE ({now.strftime('%Y-%m-%d %H:%M UTC')}) ==="]

    nw = snapshot.get("net_worth", 0)
    liquid = snapshot.get("liquid_assets", 0)
    invested = snapshot.get("investment_assets", 0)
    nc = snapshot.get("non_current_assets", 0)
    lines.append(
        f"Net worth: ${nw:,.0f} "
        f"(liquid ${liquid:,.0f}; investments ${invested:,.0f}; non-current ${nc:,.0f})"
    )

    if db is not None and user_id is not None:
        # `monthly_income_expense_medians` runs a full-window transaction
        # query — call it once here and feed both the KPI line (savings_rate)
        # and the surplus line off the same result. If the lookup fails or
        # returns None, BOTH lines drop together to keep the user-facing
        # numbers internally consistent.
        try:
            from app.engine.kpis import monthly_income_expense_medians

            medians = monthly_income_expense_medians(db, user_id=user_id)
        except Exception:
            logger.exception(
                "monthly_income_expense_medians failed; dropping KPI + surplus",
                extra={"user_id": str(user_id)},
            )
            medians = None

        kpi_line = _render_kpi_line(
            db, user_id=user_id, recurring_rules=recurring_rules, medians=medians,
        )
        if kpi_line:
            lines.append(kpi_line)
        surplus_line = _render_surplus_line(medians)
        if surplus_line:
            lines.append(surplus_line)
    else:
        # A missing wire-up of (db, user_id) silently drops the KPI line,
        # which is invisible in production. Emit a WARN so misconfiguration
        # shows up in logs / dashboards.
        logger.warning(
            "build_live_state_block called without db/user_id; "
            "KPI line dropped. db=%s user_id=%s",
            db is not None, user_id is not None,
        )

    if goals:
        # Surface duplicate-name warnings directly into the LIVE STATE so the
        # LLM disambiguates with the user before quoting numbers — this was
        # the root of repeated "Emergency Fund $6,189 vs $12,378" confusion.
        from collections import Counter
        name_counts = Counter((g.get("name") or "").strip().lower() for g in goals)
        dups = sorted({n for n, c in name_counts.items() if n and c > 1})
        if dups:
            lines.append(
                "⚠ Duplicate-name goals detected: "
                + ", ".join(f'"{n.title()}"' for n in dups)
                + " — ask the user to disambiguate before quoting numbers."
            )
        lines.append(_render_goals(goals))

    pending_bits = _render_pending(
        pending_transfer_reviews, pending_findings_count, pending_recurring_count,
    )
    if pending_bits:
        lines.append("Pending: " + ", ".join(pending_bits))

    if last_import_at:
        when = last_import_at.date().isoformat() if isinstance(last_import_at, datetime) else str(last_import_at)
        if last_import_count is not None:
            lines.append(f"Last import: {when} ({last_import_count} txns)")
        else:
            lines.append(f"Last import: {when}")

    # Portfolio block (best-effort — drops silently if user has no investment snapshots).
    if db is not None and user_id is not None:
        try:
            portfolio_lines = _portfolio_block_lines(db, str(user_id))
            if portfolio_lines:
                lines.extend(portfolio_lines)
        except Exception:
            logger.exception(
                "_portfolio_block_lines failed; dropping portfolio summary",
                extra={"user_id": str(user_id)},
            )

    lines.append("=== END STATE ===")
    return "\n".join(lines)


def _fmt_kpi(value: Optional[float], formatter) -> str:
    """Apply `formatter(value)` when value is real; otherwise emit n/a."""
    if value is None:
        return "n/a"
    try:
        return formatter(value)
    except Exception:
        return "n/a"


def _render_kpi_line(
    db,
    *,
    user_id: UUID | str,
    recurring_rules: Optional[list[RecurringRule]],
    medians: Optional[tuple[float, float]] = None,
) -> Optional[str]:
    """KPI prose: 'KPIs: Liquidity 3.1mo · Savings 28% · NW yoy +9.2% · Yield 0.4× expenses'.

    Each metric independently renders n/a when its data prerequisite isn't
    met — the LLM is told what's missing rather than getting fabricated
    numbers. KPI calls are best-effort: any unexpected exception falls
    through to None and the line is dropped.

    `medians` is the precomputed `(income, expense)` pair from
    `monthly_income_expense_medians`; the caller hoists that query so the
    surplus line can reuse the same numbers. When None, savings_rate falls
    back to n/a for this turn.
    """
    try:
        from app.engine.kpis import (
            liquidity_ratio, nw_yoy_growth, yield_on_net_worth,
        )

        liq = liquidity_ratio(
            db, user_id=user_id, recurring_rules=recurring_rules or [],
        )
        if medians is not None:
            inc_med, exp_med = medians
            save = (inc_med - exp_med) / inc_med if inc_med > 0 else None
        else:
            save = None
        growth = nw_yoy_growth(db, user_id=user_id)
        yld = yield_on_net_worth(db, user_id=user_id)
    except Exception:
        logger.exception(
            "KPI render failed; dropping KPI line",
            extra={"user_id": str(user_id)},
        )
        return None

    parts = [
        f"Liquidity {_fmt_kpi(liq, lambda v: f'{v:.1f}mo')}",
        f"Savings {_fmt_kpi(save, lambda v: f'{v * 100:.0f}%')}",
        f"NW yoy {_fmt_kpi(growth, lambda v: f'{v * 100:+.1f}%')}",
        f"Yield {_fmt_kpi(yld, lambda v: f'{v:.1f}× expenses')}",
    ]
    return "KPIs: " + " · ".join(parts)


def _render_surplus_line(
    medians: Optional[tuple[float, float]],
) -> Optional[str]:
    """Emit 'Monthly surplus: $X (income $Y − expenses $Z)' from the
    `monthly_income_expense_medians` result hoisted by the caller. Returns
    None when no transaction data exists in window — the line is then
    dropped rather than fabricated, matching the n/a-is-honest invariant.
    """
    if medians is None:
        return None
    inc, exp = medians
    surplus = inc - exp
    return (
        f"Monthly surplus: ${surplus:,.0f} "
        f"(income ${inc:,.0f} − expenses ${exp:,.0f})"
    )


def _render_goals(goals: list[dict]) -> str:
    sorted_goals = sorted(
        goals,
        key=lambda g: (
            not g.get("is_primary"),
            g.get("feasibility_score") or 100,
        ),
    )
    capped = sorted_goals[:LIVE_GOAL_CAP]
    out_lines = []
    if len(sorted_goals) > LIVE_GOAL_CAP:
        out_lines.append(
            f"Top {LIVE_GOAL_CAP} of {len(sorted_goals)} goals "
            "(primary + at-risk first):"
        )
    else:
        out_lines.append(f"Goals ({len(sorted_goals)}):")
    for g in capped:
        marker = "★" if g.get("is_primary") else " "
        target = g.get("target_amount") or 0
        progress = g.get("current_progress") or 0
        pct = (progress / target * 100) if target else 0
        target_date = g.get("target_date") or "—"
        status = (g.get("status") or "on_track").upper().replace("_", " ")
        # The goal id is rendered so the LLM can pass it to the scoring
        # tool — without it the model has historically apologized to the
        # user about "not having access to the unique goal ID required by
        # the scoring tool" (see app-tester report 2026-05-03). Wrap in
        # an HTML-comment fence so the model treats it as plumbing, not
        # prose to echo back at the user.
        gid = g.get("id") or ""
        id_suffix = f" <!--id:{gid}-->" if gid else ""
        out_lines.append(
            f"{marker} {g.get('name', '(unnamed)')}{id_suffix} — "
            f"${target:,.0f} by {target_date} | {pct:.0f}% | {status}"
        )
    return "\n".join(out_lines)


def _render_pending(
    transfers: Optional[dict],
    findings_count: int,
    recurring_count: int,
) -> list[str]:
    bits = []
    transfer_total = (transfers or {}).get("count_total", 0) if transfers else 0
    if transfer_total:
        bits.append(f"{transfer_total} transfers to review")
    if findings_count:
        bits.append(f"{findings_count} findings")
    if recurring_count:
        bits.append(f"{recurring_count} unconfirmed recurring")
    return bits


# ---- Tier 3 — RETRIEVED MEMORY ---------------------------------------------


async def build_retrieved_memory_block(
    db,
    gemini,
    *,
    user_id: UUID | str,
    query_text: str,
    profile: dict,
    accounts: list[dict],
    goals: list[dict],
    recurring_rules: Optional[list] = None,
    exclude_note_ids: Optional[list[str]] = None,
) -> str:
    """Tier 3 — top-K MMR-reranked notes for this turn.

    Embeds the query (best-effort; falls through to tag-only retrieval on
    embedding failure), calls retrieve_scored, and renders the K returned
    notes with [fact]/[pref]/[example] tag prefixes. Returns "" when the
    pool yields nothing (cold-start users, empty corpus).
    """
    try:
        scope_tags = derive_scope_tags(
            profile=profile,
            accounts=accounts or [],
            goals=goals,
            recurring_rules=[
                {"id": getattr(r, "id", None)} for r in (recurring_rules or [])
            ],
            last_user_message=query_text,
        )
    except Exception:
        logger.exception("retrieved-memory: scope_tags derivation failed")
        scope_tags = []

    query_vec = await embed_text(gemini, query_text) if query_text else None

    # Coerce exclude IDs per-element so a single corrupt row doesn't kill
    # all of Tier 3 (the broad except below would swallow it silently).
    exclude_uuids: list[UUID] = []
    for x in (exclude_note_ids or []):
        try:
            exclude_uuids.append(UUID(str(x)))
        except (ValueError, TypeError):
            logger.warning("retrieved-memory: skipping malformed exclude id %r", x)

    try:
        scored = retrieve_scored(
            db,
            user_id=UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id,
            query_vec=query_vec,
            scope_tags=scope_tags,
            top_k=TIER3_TOP_K,
            exclude_ids=exclude_uuids,
        )
    except Exception:
        logger.exception("retrieved-memory: retrieve_scored failed")
        return ""

    if not scored:
        return ""

    lines = ["=== RELEVANT TO THIS QUESTION ==="]
    for sn in scored:
        lines.append(_render_scored_note(sn))
    lines.append("=== END RELEVANT ===")
    return "\n".join(lines)


def _render_scored_note(sn: ScoredNote) -> str:
    kind = sn.note.kind
    tag = (
        "fact" if kind == NoteKind.FACT
        else "pref" if kind == NoteKind.PREFERENCE
        else "example"
    )
    return f"[{tag:<7}] {_truncate(sn.note.content, NOTE_CHAR_CAP)}"


# ---- Orchestrator -----------------------------------------------------------


async def build_financial_context(
    db,
    gemini,
    *,
    user_id: UUID | str,
    profile: dict,
    snapshot: dict,
    goals: list[dict],
    accounts: list[dict],
    last_user_message: str,
    prev_assistant_msg: Optional[str] = None,
    pending_transfer_reviews: Optional[dict] = None,
    pending_findings_count: int = 0,
    pending_recurring_count: int = 0,
    recurring_rules: Optional[list] = None,
    last_import_at: Optional[datetime] = None,
    last_import_count: Optional[int] = None,
) -> str:
    """Compose Tier 1 + Tier 2 + Tier 3 into the final context block.

    Tier 0 (`is_trivial_message`) is consulted up-front: when the user's
    message is a bare ack / chitchat the Tier 3 retrieval round trip is
    skipped, saving ~500 tokens and ~80ms while keeping Tier 1 + Tier 2
    intact (the LLM still needs identity + live state to respond at all).

    The shape, ordering, and section delimiters are stable across both
    paths so downstream prompt-cache hit rates stay high turn-to-turn.
    """
    today = date.today().isoformat()

    identity_block, anchor_ids = build_identity_block(
        db, user_id=user_id, profile=profile,
    )

    live_block = build_live_state_block(
        db=db,
        user_id=user_id,
        snapshot=snapshot,
        goals=goals,
        pending_transfer_reviews=pending_transfer_reviews,
        pending_findings_count=pending_findings_count,
        pending_recurring_count=pending_recurring_count,
        recurring_rules=recurring_rules,
        last_import_at=last_import_at,
        last_import_count=last_import_count,
    )

    sections = [
        f"Today's date: {today}",
        identity_block,
        live_block,
    ]

    if not is_trivial_message(last_user_message, prev_assistant_msg):
        retrieved_block = await build_retrieved_memory_block(
            db, gemini,
            user_id=user_id,
            query_text=last_user_message,
            profile=profile,
            accounts=accounts,
            goals=goals,
            recurring_rules=recurring_rules,
            exclude_note_ids=anchor_ids,
        )
        if retrieved_block:
            sections.append(retrieved_block)
    return "\n\n".join(sections)


# ---- Portfolio block --------------------------------------------------------


def _portfolio_block_lines(db, user_id: str) -> list[str]:
    """Compact portfolio summary for the LIVE STATE block. Returns [] when no investment snapshots."""
    try:
        from app.portfolio import snapshots as p_snapshots
        from app.portfolio.exposure import compute_exposure
    except Exception:
        return []

    accounts = (
        db.table("accounts").select("id")
        .eq("user_id", str(user_id))
        .in_("type", ["brokerage", "retirement"])
        .eq("is_active", True)
        .execute().data
    )
    if not accounts:
        return []

    aggregated: dict[str, dict] = {}
    grand_total = 0.0
    latest_dates: list[str] = []
    for a in accounts:
        snap = p_snapshots.get_latest_snapshot(db, account_id=a["id"])
        if not snap:
            continue
        latest_dates.append(snap["snapshot_date"])
        for h in snap["holdings"]:
            t = h["ticker"]
            mv = float(h["market_value"])
            grand_total += mv
            if t in aggregated:
                aggregated[t]["market_value"] += mv
            else:
                aggregated[t] = {"ticker": t, "market_value": mv}

    if grand_total <= 0:
        return []

    top = sorted(aggregated.values(), key=lambda x: x["market_value"], reverse=True)[:5]
    top_str = " · ".join(
        f"{h['ticker']} {h['market_value']/grand_total*100:.0f}%" for h in top
    )

    holdings = [{"ticker": v["ticker"], "market_value": v["market_value"]} for v in aggregated.values()]
    refs = {
        r["ticker"]: r for r in
        db.table("security_reference").select("*").in_("ticker", list(aggregated.keys())).execute().data
    }
    ac = compute_exposure(holdings, refs, dimension="asset_class")
    ac_str = " · ".join(f"{s['label']} {s['percent']:.0f}%" for s in ac)

    latest = max(latest_dates) if latest_dates else "unknown"
    return [
        f"PORTFOLIO (latest snapshot {latest}):",
        f"  Total: ${grand_total:,.0f} across {len(accounts)} investment account(s)",
        f"  Top holdings: {top_str}",
        f"  Asset class: {ac_str}",
        f"  Detailed holdings, exposure, and attribution: call portfolio_get_holdings / portfolio_get_exposure / portfolio_get_attribution.",
    ]


# ---- Helpers ----------------------------------------------------------------


def _truncate(s: str, n: int) -> str:
    if not s or len(s) <= n:
        return s
    return s[:n].rstrip() + "…"
