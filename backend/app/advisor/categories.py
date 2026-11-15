"""Transaction category names.

There are currently *two* sets in flight; they should be unified in a
follow-up PR:

- ``DB_TRANSACTION_CATEGORIES`` — the lowercase singular labels enforced by
  the ``transactions.category`` CHECK constraint in ``schema.sql``. This is
  what Plaid imports, manual imports, and direct DB writes must use.
- ``ALLOWED_CATEGORIES`` — TitleCase labels the MCP advisor tools
  (``update_transaction_category`` / ``bulk_recategorize``) currently
  validate against, plus a different set of buckets (``Bills`` / ``Health``
  vs. ``utilities`` / ``healthcare``). This means the MCP tool would reject
  every value that actually fits the DB constraint, which is a real bug —
  see docs/CLEANUP_PLAN.md cluster 6.
"""

# Canonical lowercase labels matching transactions.category CHECK constraint.
DB_TRANSACTION_CATEGORIES: tuple[str, ...] = (
    "income",
    "food",
    "transport",
    "housing",
    "utilities",
    "healthcare",
    "entertainment",
    "shopping",
    "transfer",
    "other",
)

# TitleCase labels used by the MCP advisor tools. See module docstring.
ALLOWED_CATEGORIES: frozenset[str] = frozenset({
    "Food",
    "Transport",
    "Shopping",
    "Housing",
    "Entertainment",
    "Health",
    "Bills",
    "Transfer",
    "Income",
    "Other",
})


def is_allowed(c: str | None) -> bool:
    return c in ALLOWED_CATEGORIES


# TitleCase advisor label → lowercase DB CHECK-constraint label.
# Use this when writing to transactions.category so the MCP tool's
# vocabulary doesn't trip the schema constraint.
TITLE_TO_DB_CATEGORY: dict[str, str] = {
    "Food": "food",
    "Transport": "transport",
    "Shopping": "shopping",
    "Housing": "housing",
    "Entertainment": "entertainment",
    "Health": "healthcare",
    "Bills": "utilities",
    "Transfer": "transfer",
    "Income": "income",
    "Other": "other",
}


def normalize_category_input(c: str | None) -> str | None:
    """Accept any reasonable casing/spelling the LLM emits and return the
    canonical TitleCase form. Returns None when no match. Tolerant of
    whitespace, all-lower, all-upper, and the DB-style lowercase aliases.
    """
    if not c:
        return None
    s = c.strip()
    if s in ALLOWED_CATEGORIES:
        return s
    title = s.title()
    if title in ALLOWED_CATEGORIES:
        return title
    # Reverse-lookup the DB-style alias ("healthcare" → "Health", "utilities" → "Bills")
    lower = s.lower()
    for title_key, db_val in TITLE_TO_DB_CATEGORY.items():
        if db_val == lower:
            return title_key
    return None
