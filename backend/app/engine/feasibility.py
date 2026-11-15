import math
from datetime import date
from typing import Dict, Any, Optional


def score_goal_feasibility(
    target_amount: float,
    current_progress: float,
    monthly_surplus: float,
    target_date: str,
) -> Dict[str, Any]:
    """
    Returns feasibility score (0-100), status, and months_to_goal.
    score = min(100, achievable_amount / remaining * 100)
    """
    remaining = max(0, target_amount - current_progress)

    if remaining == 0:
        return {"feasibility_score": 100.0, "status": "on_track", "months_to_goal": 0}

    target = date.fromisoformat(target_date)
    today = date.today()
    months_available = max(0, (target.year - today.year) * 12 + (target.month - today.month))

    if months_available == 0 or monthly_surplus <= 0:
        return {
            "feasibility_score": 0.0,
            "status": "off_track",
            "months_to_goal": None,
            "months_available": months_available,
            "monthly_surplus_needed": None,
        }

    achievable = monthly_surplus * months_available
    score = min(100.0, round((achievable / remaining) * 100, 1))
    months_to_goal = math.ceil(remaining / monthly_surplus)

    if score >= 90:
        status = "on_track"
    elif score >= 60:
        status = "at_risk"
    else:
        status = "off_track"

    return {
        "feasibility_score": score,
        "status": status,
        "months_to_goal": months_to_goal,
        "months_available": months_available,
        "monthly_surplus_needed": round(remaining / months_available, 2),
    }
