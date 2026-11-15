import re
from typing import Any

from pydantic import BaseModel, ValidationError

_DOLLAR_RE = re.compile(r"\$([\d,]+(?:\.\d{2})?)")


def _extract_dollar_amounts(text: str) -> list[float]:
    out = []
    for m in _DOLLAR_RE.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _extract_tool_amounts(tool_outputs: list[Any]) -> list[float]:
    amounts: list[float] = []

    def _walk(v: Any):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            amounts.append(abs(float(v)))
        elif isinstance(v, dict):
            for vv in v.values():
                _walk(vv)
        elif isinstance(v, list):
            for vv in v:
                _walk(vv)

    for o in tool_outputs:
        _walk(o)
    return amounts


_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")),
    ("plaid_access_token", re.compile(r"\baccess-(?:sandbox|development|production)-[a-z0-9-]+\b")),
    ("long_digit_run", re.compile(r"\b\d{17,}\b")),
]


def redact_pii(text: str) -> tuple[str, list[dict]]:
    warnings: list[dict] = []
    out = text
    for name, pat in _PII_PATTERNS:
        if pat.search(out):
            warnings.append({"type": "pii_redacted", "pattern": name})
            out = pat.sub("[REDACTED]", out)
    return out, warnings


# Internal-plumbing terms / tool names / raw error strings that the advisor
# tester (gap-registry G-011) repeatedly caught leaking into chat replies.
# These are post-stream rewrites: the user has already seen the streamed
# token, but the persisted chat_messages row and any subsequent context
# replay (history → next turn's prompt) get the cleaned version, so the
# model stops re-learning the leaked phrase from its own history.
_INTERNAL_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # UUIDs (any 8-4-4-4-12 hex run with optional surrounding [id: ...] / <!--id:...--> / `...` / quoted form)
    ("uuid_bracket", re.compile(r"\s*\[id:\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\s*\]", re.IGNORECASE), ""),
    ("uuid_html_fence", re.compile(r"\s*<!--id:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-->", re.IGNORECASE), ""),
    ("uuid_inline", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE), "[id]"),
    # Tool/action names. Each pattern optionally absorbs a preceding indefinite/
    # definite article so the replacement (which carries its own "the") doesn't
    # produce doubled articles like "the the simulator" or "a the simulator".
    ("tool_simulate_decision", re.compile(r"\b(?:a|an|the)\s+`?simulate_decision(?:_tool)?`?|`?simulate_decision(?:_tool)?`?", re.IGNORECASE), "the simulator"),
    ("tool_monte_carlo", re.compile(r"\b(?:a|an|the)\s+`?monte_carlo(?:_tool)?`?|`?monte_carlo(?:_tool)?`?", re.IGNORECASE), "the Monte Carlo simulator"),
    ("tool_get_transactions", re.compile(r"`?get_transactions`?", re.IGNORECASE), "transaction lookup"),
    ("tool_get_recurring_rules", re.compile(r"`?get_recurring_rules`?", re.IGNORECASE), "recurring-rules lookup"),
    ("tool_score_goal", re.compile(r"\b(?:a|an|the)\s+`?score_goal`?|`?score_goal`?", re.IGNORECASE), "the feasibility scorer"),
    ("tool_bulk_recategorize", re.compile(r"\b(?:a|an|the)\s+`?bulk_recategorize`?|`?bulk_recategorize`?", re.IGNORECASE), "the recategorize tool"),
    ("action_update_goals", re.compile(r"`?update_goals?`?", re.IGNORECASE), "goal-update"),
    ("action_delete_goals", re.compile(r"`?delete_goals?`?", re.IGNORECASE), "goal-delete"),
    ("action_new_goals", re.compile(r"`?new_goals`?", re.IGNORECASE), "goal-create"),
    # Internal context terms
    ("live_state", re.compile(r"\bLIVE STATE\b|\bLive State\b", re.IGNORECASE), "your current finances"),
    ("liquid_assets_before", re.compile(r"\bliquid_assets_before\b", re.IGNORECASE), "liquid assets before the change"),
    ("liquid_assets_after", re.compile(r"\bliquid_assets_after\b", re.IGNORECASE), "liquid assets after the change"),
    # Raw backend error strings
    ("constraint_violation", re.compile(r"\bcheck constraint violation\b", re.IGNORECASE), "an internal validation error"),
    ("integrity_error", re.compile(r"\bIntegrityError\b", re.IGNORECASE), "an internal database error"),
    ("foreign_key", re.compile(r"\bForeignKeyViolation\b", re.IGNORECASE), "an internal database error"),
    # Status enum strings used in plumbing
    ("status_at_risk", re.compile(r"`at_risk`", re.IGNORECASE), "at risk"),
    ("status_on_track", re.compile(r"`on_track`", re.IGNORECASE), "on track"),
]


def redact_internal_terms(text: str) -> tuple[str, list[dict]]:
    """Strip internal tool / column / error / status names that the advisor
    must not expose to end users. Caller-side post-stream pass — the user
    may have already seen the streamed token, but the persisted message and
    any subsequent context replay get the cleaned text.

    For tool-name patterns that may absorb a preceding article (a/an/the),
    we preserve the article's original capitalization so a sentence-start
    "The score_goal tool" becomes "The feasibility scorer tool" rather than
    "the feasibility scorer tool".
    """
    warnings: list[dict] = []
    out = text

    def _make_repl(replacement: str):
        # When the matched text starts with a capitalized article (e.g. "The"),
        # the noun-phrase replacement should also start capitalized.
        def _repl(m: "re.Match[str]") -> str:
            matched = m.group(0)
            if replacement.startswith("the ") and matched[:1].isupper() and matched.lower().startswith(("a ", "an ", "the ")):
                return replacement[0].upper() + replacement[1:]
            return replacement
        return _repl

    for name, pat, replacement in _INTERNAL_PATTERNS:
        if pat.search(out):
            warnings.append({"type": "internal_redacted", "pattern": name})
            out = pat.sub(_make_repl(replacement), out)
    return out, warnings


# Pipe-style markdown tables: a header row, optional separator row, then >=1 data rows.
# Anchored to lines that start with `|` (after optional whitespace) to avoid eating
# in-prose pipes used for `|` operators or escaped characters.
_MD_TABLE_BLOCK = re.compile(
    r"(?:^[ \t]*\|.*\|[ \t]*\n)"   # header
    r"(?:^[ \t]*\|[ \t:|\-]+\|[ \t]*\n)?"  # optional separator
    r"(?:^[ \t]*\|.*\|[ \t]*\n?)+",  # data rows
    re.MULTILINE,
)


def strip_markdown_tables(text: str) -> tuple[str, int]:
    """Remove pipe-style markdown tables from `text`. Returns (cleaned, n_stripped).

    Used post-stream when a tool result was already promoted to an inline
    `displayable_table` card — the model is told (in SYSTEM_PROMPT) not to
    duplicate the data in prose, but Gemini sometimes does it anyway. Belt
    and suspenders: strip the bubble's table so the user sees one rendering,
    not two.
    """
    n = 0
    def _sub(_m: "re.Match[str]") -> str:
        nonlocal n
        n += 1
        return ""
    cleaned = _MD_TABLE_BLOCK.sub(_sub, text)
    # Collapse any 3+ blank lines left behind into a single blank line.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), n


def check_number_consistency(
    text: str, tool_outputs: list[Any], *, tolerance_pct: float = 5.0
) -> list[dict]:
    warnings: list[dict] = []
    claimed = _extract_dollar_amounts(text)
    if not claimed:
        return warnings
    tool_amounts = _extract_tool_amounts(tool_outputs)
    if not tool_amounts:
        return warnings
    for c in claimed:
        if c == 0:
            continue
        closest = min(tool_amounts, key=lambda t: abs(t - c))
        diff_pct = abs(closest - c) / max(c, 1e-9) * 100
        if diff_pct > tolerance_pct:
            warnings.append({
                "type": "number_mismatch",
                "claimed": c,
                "closest_tool_result": closest,
                "diff_pct": round(diff_pct, 1),
            })
    return warnings


class _GoalIn(BaseModel):
    name: str
    type: str
    target_amount: float
    target_date: str


def validate_actions(raw: dict) -> tuple[dict, list[dict]]:
    warnings: list[dict] = []
    out_goals = []
    for g in raw.get("new_goals", []):
        try:
            m = _GoalIn(**g)
            out_goals.append(m.model_dump())
        except ValidationError as e:
            warnings.append({
                "type": "invalid_action",
                "reason": str(e.errors()[0]["msg"]),
                "raw": g,
            })
    return {"new_goals": out_goals}, warnings
