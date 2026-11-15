from __future__ import annotations

from typing import Dict, Iterable, List, Set, Tuple

from app.engine.recurring.rule_match import apply_rule_matches
from app.engine.recurring.schema import RecurringRule

# Income flows through monthly_income; transfers aren't spending.
_EXCLUDED_CATEGORIES = {"income", "transfer"}


def aggregate_by_category_month(
    transactions: Iterable[dict],
    recurring_rules: Iterable[RecurringRule] | None = None,
    excluded_transaction_ids: Set[str] | None = None,
) -> Dict[str, List[Tuple[str, float]]]:
    """Group expense transactions into {category: [(month, total), ...]}.

    - Drops transfers and income categories.
    - Drops transactions matched to active recurring rules (rent, salary, etc.)
      so they're not double-counted alongside the recurring projection.
    - `excluded_transaction_ids` lets callers drop transactions flagged as
      transfers in the transactions table itself (engine/transfers.py).
    """
    rules = list(recurring_rules or [])
    excluded_ids = set(excluded_transaction_ids or [])

    if rules:
        match = apply_rule_matches(transactions, rules)
        excluded_ids = excluded_ids | set(match.bindings.keys()) | set(match.suppressed)

    grouped: Dict[str, Dict[str, float]] = {}
    for t in transactions:
        if t.get("id") in excluded_ids:
            continue
        category = t.get("category") or "other"
        if category in _EXCLUDED_CATEGORIES:
            continue
        amount = float(t.get("amount") or 0)
        # Expense convention: outflows are stored as negative amounts. Skip
        # positive-amount rows here — they're refunds or income misc'd into
        # an expense category, neither of which we want skewing baselines.
        if amount >= 0:
            continue
        month = str(t.get("date", ""))[:7]
        if len(month) != 7 or month[4] != "-":
            continue
        bucket = grouped.setdefault(category, {})
        bucket[month] = bucket.get(month, 0.0) + abs(amount)

    return {
        category: sorted(months.items())
        for category, months in grouped.items()
    }
