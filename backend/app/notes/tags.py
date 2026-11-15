"""Tag helpers — entity refs + topic slug allow-list + scope derivation."""
from __future__ import annotations

from typing import Iterable, Optional

# Curated topic allow-list. Extending it is intentional and reviewable —
# the chat extractor may emit slugs not in this list, but derive_scope_tags
# only uses these for keyword matching at retrieval time.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "retirement": ["retirement", "401k", "ira", "roth", "pension"],
    "dining": ["dining", "restaurant", "eating out", "food out"],
    "debt": ["debt", "loan", "credit card", "payoff", "interest rate"],
    "kids": ["kid", "child", "baby", "daycare", "tuition"],
    "taxes": ["tax", "irs", "deduction", "withholding"],
    "housing": ["mortgage", "rent", "house", "down payment", "property"],
    "cashflow": ["cash flow", "monthly", "spending", "budget", "expenses"],
    "recurring": ["recurring", "subscription", "monthly bill", "auto-pay"],
    "investments": ["invest", "portfolio", "stock", "etf", "bond", "asset allocation", "investment", "brokerage", "index fund", "dividend"],
    "savings": ["saving", "emergency fund", "sinking fund", "rainy day", "cushion"],
    "career": ["job", "salary", "raise", "bonus", "promotion", "career", "income growth"],
    "emergency": ["emergency", "safety net", "unexpected", "job loss", "medical bill"],
    "income": ["income", "paycheck", "wage", "freelance", "side hustle"],
    "insurance": ["insurance", "health plan", "life insurance", "coverage", "premium"],
    "lifestyle": ["lifestyle", "vacation", "travel", "gym", "hobbies"],
}

RECURRING_TRIGGER_TOPICS = {"recurring", "cashflow"}


def _entity_tags(kind: str, items: Iterable[dict]) -> list[str]:
    return [f"entity:{kind}:{i['id']}" for i in items if i.get("id") is not None]


def _topic_tags(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    lowered = text.lower()
    out: set[str] = set()
    for slug, kws in TOPIC_KEYWORDS.items():
        if any(kw in lowered for kw in kws):
            out.add(f"topic:{slug}")
    return out


def derive_scope_tags(
    *,
    profile: dict,
    accounts: list[dict],
    goals: list[dict],
    recurring_rules: list[dict],
    last_user_message: Optional[str],
) -> list[str]:
    """Build the scope_tags list for a retrieval call.

    - Always includes entity:profile:<id>.
    - Includes every account/goal id (entity tags).
    - Includes recurring ids ONLY when the last user message is about recurring/cashflow.
    - Includes topic:<slug> for every slug whose keywords match the last user message.
    """
    tags: set[str] = set()
    if pid := profile.get("id"):
        tags.add(f"entity:profile:{pid}")
    tags.update(_entity_tags("account", accounts))
    tags.update(_entity_tags("goal", goals))

    topic_tags = _topic_tags(last_user_message)
    tags.update(topic_tags)

    triggered = {t.removeprefix("topic:") for t in topic_tags} & RECURRING_TRIGGER_TOPICS
    if triggered:
        tags.update(_entity_tags("recurring", recurring_rules))

    return sorted(tags)
