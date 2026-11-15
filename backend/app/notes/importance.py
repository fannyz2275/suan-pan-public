"""LLM importance scoring for user_notes.

Each note carries an `importance` (1..10) computed at insert time. Importance
becomes the `gamma` term in the Park-style retrieval score
(score = a*relevancy + b*recency + c*importance, min-max normalized).

Failure mode: Gemini errors fall through to DEFAULT_IMPORTANCE (5). The
offline backfill script re-scores rows that ended up at the default. This
keeps the chat / capture hot paths fast and resilient.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.notes.schema import DEFAULT_IMPORTANCE, NoteKind

logger = logging.getLogger(__name__)

# One small int per call. Cheap (~$0.0001/call). Never asks for explanation.
_PROMPT = (
    """System Role: You are a Senior Financial Data Architect. Your task is to evaluate a chat transcript between this user {kind} and "SuanPan," an AI finance agent.
      Rate the session's importance as a single integer from 1 to 10 based on its impact on the user's permanent financial ledger, net worth accuracy and goals alignment.

    Evaluation Criteria:

    High Score (8-10): Contains structural changes (new accounts, debt refinancing, salary changes), tax-relevant data, or permanent entity mapping (e.g., "This specific venmo user is my Landlord").

    Medium Score (5-7): Clarifies ambiguous historical transactions, sets specific budget constraints, or provides context for a one-time large capital expenditure (e.g., "The $5,000 charge was a wedding down payment").

    Low Score (1-4): General financial advice seeking, emotional venting about spending, or minor corrections to low-value, non-recurring transactions.
    
    CONTENT: {content}
    """
)


async def score_importance(
    gemini, content: str, kind: NoteKind | str
) -> int:
    """Return an importance score in [1, 10]. Falls through to 5 on any failure.

    Safe to call from any insert path; if `gemini` is None or unreachable
    the function returns the median without raising. The caller never has to
    catch.
    """
    if not content or not content.strip():
        return DEFAULT_IMPORTANCE
    if gemini is None:
        return DEFAULT_IMPORTANCE

    kind_str = kind.value if isinstance(kind, NoteKind) else str(kind)
    prompt = _PROMPT.format(kind=kind_str, content=content.strip())

    try:
        from google.genai import types
        resp = await gemini.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
        )
        return _parse(resp.text)
    except Exception:
        logger.exception("score_importance: Gemini call failed; using default")
        return DEFAULT_IMPORTANCE


_INT_1_TO_10 = re.compile(r"\b(10|[1-9])\b")


def _parse(text: Optional[str]) -> int:
    """Extract the first integer in [1, 10] from `text`. Default to 5 on miss.

    Tolerates LLM-isms like 'Importance: 7', '**7**', and trailing newlines.
    """
    if not text:
        return DEFAULT_IMPORTANCE
    m = _INT_1_TO_10.search(text)
    return int(m.group(1)) if m else DEFAULT_IMPORTANCE
