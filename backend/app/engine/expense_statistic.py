from datetime import date, timedelta
from typing import Any, Dict, List, Optional


_TRANSFER_STATUSES_TO_EXCLUDE = {"auto_paired", "user_confirmed_internal", "external"}


def compute_expense_statistic(
    transactions: List[Dict[str, Any]],
    window_days: int = 90,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Average monthly expense from negative-amount, non-transfer transactions
    in the past `window_days`."""
    if today is None:
        today = date.today()
    cutoff = today - timedelta(days=window_days)

    qualifying: List[Dict[str, Any]] = []
    for t in transactions or []:
        amount = t.get("amount")
        if amount is None or amount >= 0:
            continue
        status = t.get("transfer_status") or ""
        if status in _TRANSFER_STATUSES_TO_EXCLUDE:
            continue
        d = date.fromisoformat(t["date"]) if isinstance(t["date"], str) else t["date"]
        if d < cutoff or d > today:
            continue
        qualifying.append({"date": d, "amount": float(amount)})

    sample_size = len(qualifying)
    if sample_size == 0:
        return {"value": None, "source": "insufficient_data",
                "sample_size": 0, "window_days": window_days}

    oldest = min(t["date"] for t in qualifying)
    if (today - oldest).days < 30:
        return {"value": None, "source": "insufficient_data",
                "sample_size": sample_size, "window_days": window_days}

    total = sum(abs(t["amount"]) for t in qualifying)
    monthly_avg = round(total / window_days * 30, 2)
    return {"value": monthly_avg, "source": "computed",
            "sample_size": sample_size, "window_days": window_days}
