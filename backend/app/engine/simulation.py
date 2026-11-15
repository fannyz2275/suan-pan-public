from typing import List, Dict, Any

from app.engine.feasibility import score_goal_feasibility
from app.engine.snapshot import LIQUID_TYPES


def simulate_decision(
    decision: Dict[str, Any],
    accounts: List[Dict[str, Any]],
    goals: List[Dict[str, Any]],
    monthly_income: float,
    monthly_expenses: float,
    liquid_override: float | None = None,
) -> Dict[str, Any]:
    """
    Simulates the impact of a one-time financial decision on all goals.

    decision: {
        "description": "Buy a $35k car",
        "upfront_cost": 35000,     # one-time cash outflow
        "monthly_delta": -500,     # change to monthly expenses (negative = more expense)
        "asset_value": 35000,      # new asset created (if any)
    }

    `liquid_override` lets the caller pin liquid_before to the same value the
    LIVE STATE block displays. Without it the LLM sees two different "liquid
    assets" figures (snapshot vs sim) and reliably gets confused.
    """
    upfront = decision.get("upfront_cost", 0)
    monthly_delta = decision.get("monthly_delta", 0)

    if liquid_override is not None:
        liquid_before = float(liquid_override)
    else:
        liquid_before = sum(
            a.get("balance", 0) for a in accounts if a.get("type", "") in LIQUID_TYPES
        )
    liquid_after = liquid_before - upfront

    old_monthly_surplus = monthly_income - monthly_expenses
    # monthly_delta is negative for increased expenses, positive for decreased
    new_monthly_surplus = old_monthly_surplus + monthly_delta

    impacts = []
    for goal in goals:
        before = score_goal_feasibility(
            target_amount=goal["target_amount"],
            current_progress=goal.get("current_progress", 0),
            monthly_surplus=old_monthly_surplus,
            target_date=str(goal["target_date"]),
        )
        after = score_goal_feasibility(
            target_amount=goal["target_amount"],
            current_progress=goal.get("current_progress", 0),
            monthly_surplus=new_monthly_surplus,
            target_date=str(goal["target_date"]),
        )
        score_delta = after["feasibility_score"] - before["feasibility_score"]
        impacts.append({
            "goal_name": goal["name"],
            "score_before": before["feasibility_score"],
            "score_after": after["feasibility_score"],
            "score_delta": round(score_delta, 1),
            "status_before": before["status"],
            "status_after": after["status"],
            "months_to_goal_before": before.get("months_to_goal"),
            "months_to_goal_after": after.get("months_to_goal"),
        })

    # Worst impact first
    impacts.sort(key=lambda x: x["score_delta"])

    return {
        "decision": decision.get("description", ""),
        "liquid_assets_before": liquid_before,
        "liquid_assets_after": liquid_after,
        "monthly_surplus_before": old_monthly_surplus,
        "monthly_surplus_after": new_monthly_surplus,
        "goal_impacts": impacts,
    }
