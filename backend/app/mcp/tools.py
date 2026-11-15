from typing import Optional
from app.advisor.categories import (
    ALLOWED_CATEGORIES,
    TITLE_TO_DB_CATEGORY,
    normalize_category_input,
)
from app.engine.transfers import scan_transfers_for_user
from app.engine.snapshot import compute_snapshot
from app.engine.feasibility import score_goal_feasibility
from app.engine.simulation import simulate_decision
from app.engine.monte_carlo import run_monte_carlo
from app.engine.cashflow import project_cashflow
from app.engine.recurring.store import load_rules as _load_recurring_rules

TRANSFER_KEYWORDS = ["zelle", "venmo", "transfer", "wire", "cashapp", "paypal", "cash app"]


def rescan_transfers(db, user_id: str, window_days: int = 30) -> dict:
    """Re-run the inter-account transfer detector over the user's recent transactions.

    Updates `transactions.transfer_status` for newly detected pairs (`auto_paired`)
    and keyword-flagged orphans (`needs_review`). Safe to call any time.
    """
    result = scan_transfers_for_user(db, user_id=user_id, window_days=window_days)
    return {
        "paired": result.paired_count,
        "orphans": result.orphan_count,
        "window_days": window_days,
    }


def get_transactions(
    db, user_id: str, date_from: str, date_to: str,
    category: str | None = None,
    description_pattern: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: int = 100,
) -> list[dict]:
    q = (db.table("transactions").select("id,date,description,amount,category,account_id")
         .eq("user_id", user_id).gte("date", date_from).lte("date", date_to))
    if category:
        # Case-insensitive: the LLM may echo back category names with mixed
        # casing ("Utilities") different from how they're stored ("utilities").
        q = q.ilike("category", category)
    if description_pattern:
        q = q.ilike("description", f"%{description_pattern}%")
    if min_amount is None and max_amount is None:
        rows = q.order("date", desc=True).range(0, limit - 1).execute().data
    else:
        rows = q.order("date", desc=True).execute().data
        if min_amount is not None:
            rows = [r for r in rows if abs(r.get("amount", 0)) >= min_amount]
        if max_amount is not None:
            rows = [r for r in rows if abs(r.get("amount", 0)) <= max_amount]
        rows = rows[:limit]
    return rows


def get_spending_by_category(db, user_id: str, date_from: str, date_to: str) -> list[dict]:
    rows = (db.table("transactions").select("amount,category")
            .eq("user_id", user_id).gte("date", date_from).lte("date", date_to)
            .lt("amount", 0).execute().data)
    totals: dict[str, dict] = {}
    for r in rows:
        cat = r.get("category") or "Other"
        if cat not in totals:
            totals[cat] = {"category": cat, "total": 0.0, "count": 0, "raw_total": 0.0}
        totals[cat]["raw_total"] += abs(r["amount"])
        totals[cat]["total"] += abs(r["amount"])
        totals[cat]["count"] += 1
    result = sorted(totals.values(), key=lambda x: x["total"], reverse=True)
    for r in result:
        r["avg_transaction"] = round(r["raw_total"] / r["count"], 2) if r["count"] else 0
        r["total"] = round(r["total"], 2)
        del r["raw_total"]
    return result


def detect_transfers(db, user_id: str, date_from: str | None = None, date_to: str | None = None, limit: int = 500) -> list[dict]:
    # Default to last 30 days when caller (the LLM, or the findings-review
    # entry point) omits dates — empty params used to surface as a hard
    # validation error to the user.
    if not date_to:
        from datetime import datetime, timezone
        date_to = datetime.now(timezone.utc).date().isoformat()
    if not date_from:
        from datetime import datetime, timedelta, timezone
        date_from = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
    rows = (db.table("transactions").select("id,date,description,amount,category")
            .eq("user_id", user_id).gte("date", date_from).lte("date", date_to)
            .order("date", desc=True).range(0, limit - 1).execute().data)
    transfers = []
    for r in rows:
        desc = (r.get("description") or "").lower()
        amount = abs(r.get("amount", 0))
        reasons = []
        matched_kw = next((kw for kw in TRANSFER_KEYWORDS if kw in desc), None)
        if matched_kw:
            reasons.append(f"description contains '{matched_kw}'")
        if amount >= 100 and round(amount) % 100 == 0 and amount == round(amount):
            reasons.append("round amount")
        if (r.get("category") or "").lower() == "transfer":
            reasons.append("categorized as transfer")
        if reasons:
            transfers.append({
                "id": r["id"],
                "date": r["date"],
                "description": r["description"],
                "amount": r["amount"],
                "reason": ", ".join(reasons),
            })
    return transfers


def update_transaction_category(db, user_id: str, transaction_id: str, new_category: str) -> dict:
    canonical = normalize_category_input(new_category)
    if canonical is None:
        return {"ok": False, "error": "invalid_category", "allowed": sorted(ALLOWED_CATEGORIES)}
    new_category = canonical
    existing = (db.table("transactions").select("id,category,description")
                .eq("id", transaction_id).eq("user_id", user_id).execute().data)
    if not existing:
        return {"ok": False, "error": "Transaction not found"}
    old_category = existing[0].get("category")
    description = existing[0].get("description", "")
    db_value = TITLE_TO_DB_CATEGORY[new_category]
    update_result = db.table("transactions").update({"category": db_value}).eq("id", transaction_id).eq("user_id", user_id).execute()
    if not update_result.data:
        return {"ok": False, "error": "Update failed"}

    # Best-effort policy derivation. The user's correction succeeded above;
    # this side effect makes future categorizations of the same description
    # auto-apply once the threshold is met. Failures here are logged + dropped.
    try:
        from app.policy import categorize as policy_categorize
        policy_categorize.derive_from_correction(
            db, user_id=user_id, description=description, new_category=new_category,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "policy.categorize.derive_from_correction failed for txn=%s", transaction_id,
        )

    return {
        "ok": True,
        "transaction_id": transaction_id,
        "description": description,
        "old_category": old_category,
        "new_category": new_category,
    }


def compare_spending_periods(
    db, user_id: str,
    period_a_start: str, period_a_end: str,
    period_b_start: str, period_b_end: str,
) -> dict:
    def totals_by_cat(date_from: str, date_to: str) -> dict[str, float]:
        rows = (db.table("transactions").select("amount,category")
                .eq("user_id", user_id).gte("date", date_from).lte("date", date_to)
                .lt("amount", 0).execute().data)
        t: dict[str, float] = {}
        for r in rows:
            cat = r.get("category") or "Other"
            t[cat] = t.get(cat, 0.0) + abs(r["amount"])
        return t

    a = totals_by_cat(period_a_start, period_a_end)
    b = totals_by_cat(period_b_start, period_b_end)
    all_cats = sorted(set(a) | set(b))
    by_category = []
    for cat in all_cats:
        a_val = a.get(cat, 0.0)
        b_val = b.get(cat, 0.0)
        delta = b_val - a_val
        pct = round(delta / a_val * 100, 1) if a_val > 0 else None
        by_category.append({
            "category": cat,
            "period_a": round(a_val, 2),
            "period_b": round(b_val, 2),
            "delta": round(delta, 2),
            "pct_change": pct,
        })
    total_a = round(sum(a.values()), 2)
    total_b = round(sum(b.values()), 2)
    return {"by_category": by_category, "total_a": total_a, "total_b": total_b, "delta": round(total_b - total_a, 2)}


def bulk_recategorize(db, user_id: str, description_pattern: str, new_category: str, date_from: str, date_to: str, dry_run: bool = True) -> dict:
    canonical = normalize_category_input(new_category)
    if canonical is None:
        return {"matched": [], "new_category": new_category or "", "updated_count": 0, "failed_ids": [], "mode": "error",
                "error": "invalid_category", "allowed": sorted(ALLOWED_CATEGORIES)}
    new_category = canonical
    db_value = TITLE_TO_DB_CATEGORY[new_category]
    rows = (db.table("transactions").select("id,date,description,amount,category")
            .eq("user_id", user_id).gte("date", date_from).lte("date", date_to).execute().data)
    pattern = description_pattern.lower()
    matched_raw = [r for r in rows if pattern in (r.get("description") or "").lower()]
    matched = [{**r, "old_category": r.get("category")} for r in matched_raw]
    for item in matched:
        item.pop("category", None)
    if dry_run or not matched:
        return {"matched": matched, "new_category": new_category, "updated_count": 0, "failed_ids": [], "mode": "preview"}
    updated_ids = []
    failed_ids = []
    for tid in [r["id"] for r in matched]:
        res = db.table("transactions").update({"category": db_value}).eq("id", tid).eq("user_id", user_id).execute()
        (updated_ids if res.data else failed_ids).append(tid)

    # Bulk recategorize is a strong signal — call derive once for the
    # description pattern. The threshold (PROMOTION_THRESHOLD=2) is met
    # immediately because we just wrote N>=1 matching txns under new_category.
    if updated_ids:
        try:
            from app.policy import categorize as policy_categorize
            policy_categorize.derive_from_correction(
                db, user_id=user_id, description=description_pattern, new_category=new_category,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "policy.categorize.derive_from_correction failed for bulk pattern=%r",
                description_pattern,
            )

    return {"matched": matched, "new_category": new_category, "updated_count": len(updated_ids), "failed_ids": failed_ids, "mode": "executed"}


# ---- Engine functions exposed as MCP tools ---------------------------------
#
# Each wrapper loads the user's data from the DB + calls the pure engine fn.
# The engine modules themselves stay HTTP-blind and DB-blind so they remain
# trivial to unit-test in isolation; the wrappers carry all the IO.


def _load_profile(db, user_id: str) -> dict:
    rows = db.table("profiles").select("*").eq("id", user_id).execute().data
    return rows[0] if rows else {}


def _load_accounts(db, user_id: str) -> list[dict]:
    return (
        db.table("accounts").select("*")
        .eq("user_id", user_id).eq("is_active", True).execute().data
    ) or []


def _load_active_goals(db, user_id: str) -> list[dict]:
    return (
        db.table("goals").select("*")
        .eq("user_id", user_id).eq("is_active", True).execute().data
    ) or []


def _monthly_income_expenses(db, user_id: str) -> tuple[float, float]:
    """Median monthly income + expenses, computed from real transactions
    over the rolling LOOKBACK_MONTHS window. Returns (0, 0) for cold-start
    users with no transactions — the caller treats that as a zero-surplus
    baseline.

    The dollar-amount rule (see README.md, "Carry your priorities into the next conversation"): the legacy
    profile.annual_income / profile.monthly_expenses columns were dropped
    in PR-A's migration. All dollar reads now route through the transaction
    median engine.
    """
    from app.engine.kpis import monthly_income_expense_medians

    medians = monthly_income_expense_medians(db, user_id=user_id)
    if medians is None:
        return 0.0, 0.0
    return medians


def get_snapshot(db, user_id: str) -> dict:
    """Compute the user's net-worth snapshot (liquid / investments / non-current
    / liabilities + total). Cheap; safe to call any time."""
    return compute_snapshot(_load_accounts(db, user_id))


def score_goal(db, user_id: str, goal_id: str) -> dict:
    """Score a single goal's feasibility (0-100) given the user's current
    monthly surplus and progress. Returns {feasibility_score, status,
    months_to_goal, ...}. Errors if the goal id doesn't belong to the user.

    Accepts either a UUID or a goal name (case-insensitive). If multiple
    active goals share the name, returns an error listing them so the
    caller can disambiguate.
    """
    import re as _re
    _UUID_RE = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.IGNORECASE)

    rows: list[dict] = []
    if _UUID_RE.match(goal_id or ""):
        rows = (
            db.table("goals").select("*")
            .eq("id", goal_id).eq("user_id", user_id).limit(1).execute().data
        ) or []
    if not rows:
        # Name fallback. Case-insensitive, exact match.
        candidates = (
            db.table("goals").select("*")
            .eq("user_id", user_id).eq("is_active", True)
            .ilike("name", goal_id or "").execute().data
        ) or []
        if len(candidates) == 1:
            rows = candidates
        elif len(candidates) > 1:
            return {
                "error": "goal name is ambiguous",
                "matches": [{"id": c["id"], "name": c["name"], "target_amount": c.get("target_amount")} for c in candidates],
            }
    if not rows:
        return {"error": "goal not found"}
    g = rows[0]
    monthly_income, monthly_expenses = _monthly_income_expenses(db, user_id)
    monthly_surplus = monthly_income - monthly_expenses
    return score_goal_feasibility(
        target_amount=float(g.get("target_amount") or 0),
        current_progress=float(g.get("current_progress") or 0),
        monthly_surplus=monthly_surplus,
        target_date=str(g.get("target_date") or ""),
    )


def simulate_decision_tool(
    db, user_id: str, *,
    description: str,
    upfront_cost: float = 0.0,
    monthly_delta: float = 0.0,
    asset_value: float = 0.0,
) -> dict:
    """Project the impact of a one-time financial decision on every goal.
    Wraps engine.simulation.simulate_decision with the user's current
    accounts, goals, and transaction-derived monthly cashflow as inputs."""
    monthly_income, monthly_expenses = _monthly_income_expenses(db, user_id)
    accounts = _load_accounts(db, user_id)
    snap = compute_snapshot(accounts)
    return simulate_decision(
        decision={
            "description": description,
            "upfront_cost": upfront_cost,
            "monthly_delta": monthly_delta,
            "asset_value": asset_value,
        },
        accounts=accounts,
        goals=_load_active_goals(db, user_id),
        monthly_income=monthly_income,
        monthly_expenses=monthly_expenses,
        liquid_override=float(snap.get("liquid_assets") or 0),
    )


def monte_carlo_tool(
    db, user_id: str, *,
    years: int,
    monthly_contribution: float | None = None,
    initial_portfolio: float | None = None,
    target_amount: float | None = None,
    annual_return_mean: float = 0.07,
    annual_return_std: float = 0.15,
    inflation_rate: float = 0.03,
) -> dict:
    """Stochastic portfolio projection. Defaults `initial_portfolio` to the
    user's current investment_assets and `monthly_contribution` to their
    monthly surplus when not provided."""
    if years <= 0:
        return {"error": "years must be > 0 — provide a positive projection horizon (e.g. years=30)"}
    accounts = _load_accounts(db, user_id)
    snap = compute_snapshot(accounts)
    monthly_income, monthly_expenses = _monthly_income_expenses(db, user_id)
    if initial_portfolio is None:
        initial_portfolio = float(snap.get("investment_assets") or 0)
    if monthly_contribution is None:
        monthly_contribution = max(0.0, monthly_income - monthly_expenses)
    if initial_portfolio == 0 and monthly_contribution == 0:
        return {
            "error": (
                "Cannot project: both initial_portfolio and monthly_contribution are 0. "
                "Provide at least one positive value — e.g. initial_portfolio=50000 "
                "or monthly_contribution=500."
            )
        }
    result = run_monte_carlo(
        initial_portfolio=initial_portfolio,
        monthly_contribution=monthly_contribution,
        years=years,
        target_amount=target_amount,
        annual_return_mean=annual_return_mean,
        annual_return_std=annual_return_std,
        inflation_rate=inflation_rate,
    )
    # Echo the inputs the simulator actually used so a "rerun with the same
    # parameters" question produces byte-identical results — defaults are
    # snapshot-derived and would otherwise drift mid-session.
    result["effective_inputs"] = {
        "initial_portfolio": round(float(initial_portfolio), 2),
        "monthly_contribution": round(float(monthly_contribution), 2),
        "years": years,
        "target_amount": target_amount,
        "annual_return_mean": annual_return_mean,
        "annual_return_std": annual_return_std,
        "inflation_rate": inflation_rate,
    }
    return result


def _resolve_goal_id(db, user_id: str, goal_id_or_name: str) -> tuple[str | None, list[dict]]:
    """Resolve a UUID-or-name input to a single goal id.

    Returns (id, candidates). When `id` is set, the resolution succeeded.
    When `id` is None, `candidates` carries 0 or more matches the caller
    can present back to the user for disambiguation.
    """
    import re as _re
    _UUID_RE = _re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", _re.IGNORECASE)
    if _UUID_RE.match(goal_id_or_name or ""):
        rows = (
            db.table("goals").select("*")
            .eq("id", goal_id_or_name).eq("user_id", user_id).limit(1).execute().data
        ) or []
        if rows:
            return rows[0]["id"], rows
        return None, []
    candidates = (
        db.table("goals").select("*")
        .eq("user_id", user_id).eq("is_active", True)
        .ilike("name", goal_id_or_name or "").execute().data
    ) or []
    if len(candidates) == 1:
        return candidates[0]["id"], candidates
    return None, candidates


def update_goal(
    db, user_id: str, *, goal_id: str,
    name: str | None = None,
    target_amount: float | None = None,
    target_date: str | None = None,
) -> dict:
    """Update a single goal. Only the fields passed are changed.
    Returns the updated row, or {error, ...} when ambiguous / not found.
    """
    resolved_id, candidates = _resolve_goal_id(db, user_id, goal_id)
    if resolved_id is None:
        if len(candidates) > 1:
            return {
                "error": "goal name is ambiguous",
                "matches": [{"id": c["id"], "name": c["name"], "target_amount": c.get("target_amount")} for c in candidates],
            }
        return {"error": "goal not found"}
    patch: dict = {}
    if name is not None:
        patch["name"] = name
    if target_amount is not None:
        patch["target_amount"] = float(target_amount)
    if target_date is not None:
        patch["target_date"] = target_date
    if not patch:
        return {"error": "no fields to update", "ok": False}
    result = (
        db.table("goals").update(patch)
        .eq("id", resolved_id).eq("user_id", user_id).execute()
    )
    if not result.data:
        return {"error": "update failed", "ok": False}
    row = result.data[0]
    return {
        "ok": True,
        "id": row["id"],
        "name": row.get("name"),
        "target_amount": row.get("target_amount"),
        "target_date": str(row.get("target_date") or ""),
        "changed_fields": sorted(patch.keys()),
    }


def delete_goal(db, user_id: str, *, goal_id: str) -> dict:
    """Soft-delete a goal (sets is_active=False). Idempotent."""
    resolved_id, candidates = _resolve_goal_id(db, user_id, goal_id)
    if resolved_id is None:
        if len(candidates) > 1:
            return {
                "error": "goal name is ambiguous",
                "matches": [{"id": c["id"], "name": c["name"], "target_amount": c.get("target_amount")} for c in candidates],
            }
        return {"error": "goal not found"}
    result = (
        db.table("goals").update({"is_active": False})
        .eq("id", resolved_id).eq("user_id", user_id).execute()
    )
    if not result.data:
        return {"error": "delete failed", "ok": False}
    return {"ok": True, "id": resolved_id, "name": result.data[0].get("name")}


def find_similar_goal(db, user_id: str, *, candidate_name: str) -> dict:
    """Return the closest existing-goal name to `candidate_name`.
    Uses a simple token-overlap + difflib ratio so the LLM can decide
    whether to update_goal vs propose a new goal.
    """
    from difflib import SequenceMatcher

    rows = (
        db.table("goals").select("id,name,target_amount,target_date")
        .eq("user_id", user_id).eq("is_active", True).execute().data
    ) or []
    if not rows:
        return {"match": None, "score": 0.0, "all": []}
    cand_norm = (candidate_name or "").strip().lower()
    best = None
    best_score = 0.0
    for r in rows:
        existing = (r.get("name") or "").strip().lower()
        if not existing:
            continue
        ratio = SequenceMatcher(None, existing, cand_norm).ratio()
        # Token-overlap boost: "Wedding" should match "wedding fund" strongly.
        cand_tokens = set(cand_norm.split())
        exist_tokens = set(existing.split())
        if cand_tokens and exist_tokens:
            overlap = len(cand_tokens & exist_tokens) / max(len(cand_tokens | exist_tokens), 1)
            ratio = max(ratio, overlap)
        if ratio > best_score:
            best, best_score = r, ratio
    return {
        "match": (
            {
                "id": best["id"], "name": best["name"],
                "target_amount": best.get("target_amount"),
                "target_date": str(best.get("target_date") or ""),
            }
            if best else None
        ),
        "score": round(best_score, 3),
        "all": [{"name": r.get("name")} for r in rows],
    }


def find_goal_by_name(db, user_id: str, *, name: str) -> dict:
    """Fuzzy name lookup for a goal by partial or full name — bypasses the
    context window cap so the advisor can find goals not in the top-10 list.

    Returns the best-matching active goal dict (with id, name, target_amount,
    target_date, feasibility_score, status) or {"error": "goal not found"}.
    Useful when the user references a goal by name that may not be in the
    current LIVE STATE context block.
    """
    from difflib import SequenceMatcher

    rows = (
        db.table("goals").select("id,name,target_amount,target_date,feasibility_score,status,current_progress")
        .eq("user_id", user_id).eq("is_active", True).execute().data
    ) or []
    if not rows:
        return {"error": "goal not found", "all_goal_names": []}

    name_norm = (name or "").strip().lower()
    best = None
    best_score = 0.0
    for r in rows:
        existing = (r.get("name") or "").strip().lower()
        if not existing:
            continue
        ratio = SequenceMatcher(None, existing, name_norm).ratio()
        cand_tokens = set(name_norm.split())
        exist_tokens = set(existing.split())
        if cand_tokens and exist_tokens:
            overlap = len(cand_tokens & exist_tokens) / max(len(cand_tokens | exist_tokens), 1)
            ratio = max(ratio, overlap)
        if ratio > best_score:
            best, best_score = r, ratio

    all_names = [r.get("name") for r in rows if r.get("name")]
    if best is None or best_score < 0.3:
        return {"error": "goal not found", "all_goal_names": all_names}
    return {
        "id": best["id"],
        "name": best["name"],
        "target_amount": best.get("target_amount"),
        "target_date": str(best.get("target_date") or ""),
        "feasibility_score": best.get("feasibility_score"),
        "status": best.get("status"),
        "current_progress": best.get("current_progress"),
        "match_score": round(best_score, 3),
        "all_goal_names": all_names,
    }


def list_recurring_rules(
    db, user_id: str, *,
    min_monthly_amount: float | None = None,
    frequency: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """List the user's detected recurring rules. Filterable by minimum
    monthly-equivalent amount, frequency (monthly/weekly/...), and status.

    Returns a compact dict per rule (no UUIDs, no sample_transaction_ids)
    so the LLM can rank/cancel without leaking plumbing into chat.
    """
    from uuid import UUID
    from app.engine.cashflow import FREQ_PER_YEAR

    try:
        rules = _load_recurring_rules(db, UUID(user_id))
    except Exception:
        rules = []

    out = []
    for r in rules:
        if status and (r.status if isinstance(r.status, str) else r.status.value) != status:
            continue
        freq_val = r.frequency if isinstance(r.frequency, str) else r.frequency.value
        if frequency and freq_val != frequency:
            continue
        monthly = r.amount_median * FREQ_PER_YEAR[r.frequency] / 12
        if min_monthly_amount is not None and abs(monthly) < min_monthly_amount:
            continue
        out.append({
            "keyword": r.keyword,
            "frequency": freq_val,
            "direction": r.direction if isinstance(r.direction, str) else r.direction.value,
            "amount_median": round(r.amount_median, 2),
            "monthly_equivalent": round(monthly, 2),
            "confidence": round(r.confidence, 2),
            "status": r.status if isinstance(r.status, str) else r.status.value,
            "occurrences_observed": r.occurrences_observed,
            "last_seen_date": str(r.last_seen_date) if r.last_seen_date else None,
        })
    out.sort(key=lambda x: x["monthly_equivalent"], reverse=True)
    return out


def compute_annuity(
    *,
    solve_for: str,
    annual_rate: float,
    pmt: float | None = None,
    fv: float | None = None,
    months: int | None = None,
) -> dict:
    """Deterministic FV-of-ordinary-annuity calculator. No DB or user_id needed.

    solve_for must be one of:
      "months" — given pmt + fv + annual_rate, return months to reach fv (rounds up)
      "fv"     — given pmt + months + annual_rate, return future value accumulated
      "pmt"    — given fv + months + annual_rate, return required monthly payment

    Formula: FV = PMT * ((1+r)^n - 1) / r   where r = annual_rate / 12
    Inverse:  n = ln(FV*r/PMT + 1) / ln(1+r)
    """
    import math

    VALID = {"months", "fv", "pmt"}
    if solve_for not in VALID:
        return {"error": f"solve_for must be one of {sorted(VALID)}, got {solve_for!r}"}
    if annual_rate <= 0 or annual_rate >= 1:
        return {"error": "annual_rate must be a decimal between 0 and 1 (e.g. 0.07 for 7%)"}

    r = annual_rate / 12

    if solve_for == "months":
        if pmt is None or fv is None:
            return {"error": "solve_for='months' requires pmt and fv"}
        if pmt <= 0:
            return {"error": "pmt must be positive"}
        if fv <= 0:
            return {"error": "fv must be positive"}
        n_exact = math.log(fv * r / pmt + 1) / math.log(1 + r)
        n_int = math.ceil(n_exact)
        fv_at_n = pmt * ((1 + r) ** n_int - 1) / r
        years, mo = divmod(n_int, 12)
        years_months_str = f"{years}yr {mo}mo" if years else f"{mo}mo"
        result: dict = {
            "solve_for": "months",
            "months": n_int,
            "months_exact": round(n_exact, 4),
            "years_months": years_months_str,
            "fv_at_months": round(fv_at_n, 2),
            "inputs": {"pmt": pmt, "fv": fv, "annual_rate": annual_rate},
        }
        if n_exact > 1200:
            result["warning"] = (
                f"This target takes {years_months_str} (>{round(n_exact/12, 1)} years) at the given "
                f"payment and rate. Consider increasing your monthly contribution to shorten the timeline."
            )
        return result

    if solve_for == "fv":
        if pmt is None or months is None:
            return {"error": "solve_for='fv' requires pmt and months"}
        if pmt <= 0:
            return {"error": "pmt must be positive"}
        if months <= 0:
            return {"error": "months must be positive"}
        fv_result = pmt * ((1 + r) ** months - 1) / r
        years, mo = divmod(months, 12)
        years_months_str = f"{years}yr {mo}mo" if years else f"{mo}mo"
        return {
            "solve_for": "fv",
            "fv": round(fv_result, 2),
            "months": months,
            "years_months": years_months_str,
            "inputs": {"pmt": pmt, "months": months, "annual_rate": annual_rate},
        }

    # solve_for == "pmt"
    if fv is None or months is None:
        return {"error": "solve_for='pmt' requires fv and months"}
    if fv <= 0:
        return {"error": "fv must be positive"}
    if months <= 0:
        return {"error": "months must be positive"}
    pmt_result = fv * r / ((1 + r) ** months - 1)
    years, mo = divmod(months, 12)
    years_months_str = f"{years}yr {mo}mo" if years else f"{mo}mo"
    return {
        "solve_for": "pmt",
        "pmt": round(pmt_result, 2),
        "fv": fv,
        "months": months,
        "years_months": years_months_str,
        "inputs": {"fv": fv, "months": months, "annual_rate": annual_rate},
    }


def _user_owns_investment_account(db, user_id: str, account_id: str) -> bool:
    """Return True iff user_id owns an active brokerage/retirement account with this id."""
    rows = (
        db.table("accounts").select("id")
        .eq("id", account_id).eq("user_id", user_id)
        .in_("type", ["brokerage", "retirement"])
        .eq("is_active", True)
        .limit(1).execute().data
    )
    return bool(rows)


def _latest_in_series(series: dict, on_date) -> Optional[float]:
    candidates = [d for d in series.keys() if d <= on_date]
    return series[max(candidates)] if candidates else None


def _yield_change_bps_from_series(series: dict, from_d, to_d) -> Optional[float]:
    start = _latest_in_series(series, from_d)
    end = _latest_in_series(series, to_d)
    if start is None or end is None:
        return None
    return round((end - start) * 100, 1)


def project_cashflow_tool(
    db, user_id: str, *, months: int = 12,
) -> list[dict]:
    """Month-by-month cash-balance projection. Pulls the user's liquid
    assets, transaction-derived monthly cashflow, and RSU vesting events
    from accounts into engine.cashflow.project_cashflow.

    Recurring rules are intentionally NOT passed here: the monthly_income and
    monthly_expenses figures are already transaction-derived medians that include
    every recurring payment already recorded in the user's history. Passing
    recurring_rules alongside those medians would double-count fixed charges
    (e.g. a $3,300/mo transfer rule + the same $3,300 already in expense medians
    would inflate the projection by that amount each month).
    """
    accounts = _load_accounts(db, user_id)
    snap = compute_snapshot(accounts)
    monthly_income, monthly_expenses = _monthly_income_expenses(db, user_id)

    vesting_events: list[dict] = []
    for a in accounts:
        if a.get("type") == "rsu" and isinstance(a.get("vesting_schedule"), list):
            vesting_events.extend(a["vesting_schedule"])

    return project_cashflow(
        liquid_assets=float(snap.get("liquid_assets") or 0),
        monthly_income=monthly_income,
        monthly_expenses=monthly_expenses,
        months=months,
        vesting_events=vesting_events or None,
    )


def get_account_balance_history(
    db, user_id: str, *,
    account_id: str | None = None,
    months: int = 3,
) -> list[dict]:
    """Per-account monthly balance history for the past `months` months.

    Returns a list of {month, account_name, account_type, balance} rows
    sorted oldest-first. When account_id is None, returns history for all
    of the user's active accounts. When account_id is provided, scopes to
    that single account.

    Used by the advisor to answer "why is my checking lower than last month?"
    and similar account-level trend questions that the aggregate snapshot
    cannot answer.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30 * months)).isoformat()

    accounts = (
        db.table("accounts").select("id,name,type")
        .eq("user_id", user_id).eq("is_active", True).execute().data
    ) or []
    if account_id is not None:
        accounts = [a for a in accounts if a["id"] == account_id]
    if not accounts:
        return []

    acct_by_id = {a["id"]: a for a in accounts}
    acct_ids = list(acct_by_id.keys())

    history = (
        db.table("account_balance_history").select("account_id,balance,as_of")
        .eq("user_id", user_id)
        .in_("account_id", acct_ids)
        .gte("as_of", cutoff)
        .order("as_of")
        .execute().data
    ) or []

    # Roll up to (account_id, yyyy-mm) → last balance seen in that month.
    by_acct_month: dict[tuple[str, str], float] = {}
    for r in history:
        ym = str(r["as_of"])[:7]
        by_acct_month[(r["account_id"], ym)] = float(r["balance"] or 0)

    out: list[dict] = []
    for (aid, ym), bal in sorted(by_acct_month.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        acct = acct_by_id.get(aid, {})
        out.append({
            "month": ym,
            "account_name": acct.get("name", "Unknown"),
            "account_type": acct.get("type", "unknown"),
            "balance": round(bal, 2),
        })
    return out


def portfolio_get_holdings(db, user_id: str, *, account_id: str | None = None, as_of: str | None = None) -> list[dict]:
    """Aggregated current holdings across investment accounts (or one account if specified).

    Returns a list of {ticker, quantity, price, market_value, percent, cost_basis,
    unrealized_gain}. Used by the advisor to answer "what do I own?".
    """
    from app.portfolio import snapshots as p_snapshots

    if account_id is not None and not _user_owns_investment_account(db, user_id, account_id):
        return [{"error": "account not found"}]

    if account_id is None:
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", user_id)
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]
    else:
        account_ids = [account_id]

    aggregated: dict[str, dict] = {}
    grand_total = 0.0
    for aid in account_ids:
        snap = p_snapshots.get_latest_snapshot(db, account_id=aid)
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
    result = [
        {
            "ticker": v["ticker"],
            "quantity": round(v["quantity"], 4),
            "price": round(v["price"], 2),
            "market_value": round(v["market_value"], 2),
            "percent": round(v["market_value"] / grand_total * 100, 2),
            "cost_basis": v["cost_basis"],
            "unrealized_gain": v["unrealized_gain"],
        }
        for v in sorted(aggregated.values(), key=lambda x: x["market_value"], reverse=True)
    ]
    return result


def portfolio_get_attribution(
    db, user_id: str, *,
    from_date: str, to_date: str, account_id: str | None = None,
) -> dict:
    """Decompose period change into market / contributions / withdrawals / dividends /
    trades / unattributed. Returns the decomposition + macro context + per-bucket
    narrative hints (one-sentence root-cause strings).
    """
    from datetime import date as _date
    from app.portfolio.attribution import compute_attribution
    from app.portfolio import reval as reval_engine
    from app.portfolio import reference as ref_module
    from app.portfolio import snapshots as p_snapshots
    from app.portfolio.fred import fetch_fred_series

    fd = _date.fromisoformat(from_date)
    td = _date.fromisoformat(to_date)

    if account_id is not None and not _user_owns_investment_account(db, user_id, account_id):
        return {"error": "account not found"}

    if account_id is None:
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", user_id)
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]
    else:
        account_ids = [account_id]

    if not account_ids:
        return {"error": "no investment accounts found"}

    snaps = p_snapshots.get_snapshots_in_window(db, account_ids, fd, td)
    if not snaps:
        return {"error": "no snapshots in window"}

    all_tickers = {h["ticker"] for s in snaps for h in s["holdings"]}
    prices = ref_module.get_prices(db, list(all_tickers), fd, td)

    start_total = 0.0
    end_total = 0.0
    for aid in account_ids:
        acct_snaps = [s for s in snaps if s["account_id"] == aid]
        series = reval_engine.timeseries(acct_snaps, prices, fd, td)
        if series:
            start_total += series[0]["total_value"]
            end_total += series[-1]["total_value"]

    txns = (
        db.table("investment_transactions").select("*")
        .eq("user_id", user_id)
        .gte("date", from_date).lte("date", to_date)
        .order("date").execute().data
    )
    if account_id is not None:
        txns = [t for t in txns if t["account_id"] == account_id]

    decomp = compute_attribution(
        start_value=start_total, end_value=end_total, transactions=txns,
    )

    ten_y = fetch_fred_series("DGS10", fd, td)
    cpi = fetch_fred_series("CPIAUCSL", fd, td)
    spy_prices = ref_module.get_prices(db, ["SPY"], fd, td)
    spy_dates = sorted(d for (t, d) in spy_prices.keys() if t == "SPY")

    macro = {
        "ten_year_yield_change_bps": _yield_change_bps_from_series(ten_y, fd, td) if ten_y else None,
        "cpi_yoy_at_end": _latest_in_series(cpi, td) if cpi else None,
        "spy_period_return_pct": (
            round(
                (spy_prices[("SPY", spy_dates[-1])] - spy_prices[("SPY", spy_dates[0])])
                / spy_prices[("SPY", spy_dates[0])] * 100, 2
            ) if len(spy_dates) >= 2 and spy_prices[("SPY", spy_dates[0])] > 0 else None
        ),
    }

    # Narrative hints — one-sentence root causes per bucket. The advisor is free
    # to use, edit, or ignore these; they exist to model the form (per spec § Borrowed patterns).
    hints: list[str] = []
    if abs(decomp["market"]) >= 100:
        spy = macro.get("spy_period_return_pct")
        spy_clause = f" while SPY moved {spy:+.1f}%" if spy is not None else ""
        sign = "+" if decomp["market"] >= 0 else ""
        if start_total > 0:
            pct_clause = f" — your holdings moved {sign}{decomp['market']/start_total*100:.1f}% in the period"
        else:
            pct_clause = ""
        hints.append(
            f"{sign}${abs(decomp['market']):,.0f} from market{pct_clause}{spy_clause}."
        )
    if abs(decomp["contributions"]) >= 100:
        hints.append(
            f"+${decomp['contributions']:,.0f} from contributions — deposits/transfers in during the period."
        )
    if abs(decomp["withdrawals"]) >= 100:
        hints.append(
            f"−${abs(decomp['withdrawals']):,.0f} from withdrawals — cash out during the period."
        )
    if abs(decomp["dividends"]) >= 10:
        hints.append(
            f"+${decomp['dividends']:,.0f} from dividends/interest paid into cash."
        )
    if abs(decomp["trades"]) >= 100:
        basis_note = "" if decomp["trades_has_basis"] else " (cost basis missing on at least one sell — this is the cash impact, not realized P&L)"
        sign = "+" if decomp["trades"] >= 0 else "−"
        hints.append(
            f"{sign}${abs(decomp['trades']):,.0f} from trades{basis_note}."
        )
    if abs(decomp["unattributed"]) >= 100:
        sign = "+" if decomp["unattributed"] >= 0 else "−"
        hints.append(
            f"{sign}${abs(decomp['unattributed']):,.0f} unattributed — period change isn't fully explained by recorded flows + estimated market move; usually means an investment txn is missing or a snapshot has stale prices."
        )

    return {
        "from_date": from_date, "to_date": to_date,
        **decomp,
        "macro_context": macro,
        "narrative_hints": hints,
    }


def portfolio_get_exposure(db, user_id: str, *, dimension: str = "asset_class", account_id: str | None = None) -> list[dict]:
    """3-dim allocation (asset class / sector / region) with top-10 ETF look-through."""
    from app.portfolio import snapshots as p_snapshots
    from app.portfolio.exposure import compute_exposure

    if dimension not in ("asset_class", "sector", "region"):
        return [{"error": "dimension must be one of: asset_class, sector, region"}]

    if account_id is not None and not _user_owns_investment_account(db, user_id, account_id):
        return [{"error": "account not found"}]

    if account_id is None:
        rows = (
            db.table("accounts").select("id")
            .eq("user_id", user_id)
            .in_("type", ["brokerage", "retirement"])
            .eq("is_active", True)
            .execute().data
        )
        account_ids = [r["id"] for r in rows]
    else:
        account_ids = [account_id]

    holdings: list[dict] = []
    for aid in account_ids:
        snap = p_snapshots.get_latest_snapshot(db, account_id=aid)
        if snap:
            holdings.extend(snap["holdings"])
    if not holdings:
        return []

    tickers = list({h["ticker"] for h in holdings})
    ref_rows = db.table("security_reference").select("*").in_("ticker", tickers).execute().data
    refs = {r["ticker"]: r for r in ref_rows}

    return compute_exposure(holdings, refs, dimension=dimension)

