from __future__ import annotations
from app.provider_credentials.scope import gemini_client

import json
import logging
import re
import statistics
from typing import List, Optional
from uuid import UUID

from google import genai
from google.genai import types

from app.config import settings
from app.engine.recurring.cluster import CandidateCluster
from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)

logger = logging.getLogger(__name__)

_LLM_LOW = 0.40
_LLM_HIGH = 0.75
_DESC_VARIANCE_THRESHOLD = 0.40
_STABILITY_OK = 0.80

_MODEL_NAME = "gemini-2.5-flash"

_PROMPT_TEMPLATE = """You are a disambiguation assistant for a personal-finance recurring-payment detector.
Given a candidate cluster of transactions and a list of confirmed rules the user has previously reviewed,
return a RecurringRule JSON for this cluster with the best display keyword, matching pattern, and your confidence.

Confirmed rules (few-shot examples):
{few_shot}

Candidate cluster:
Descriptions: {descriptions}
Amounts: {amounts}
Heuristic confidence: {heuristic}

Respond ONLY with JSON matching this shape:
{{"keyword": "...", "normalized_key_pattern": "...", "confidence": 0.0}}
"""


def should_use_llm(
    *, confidence: float, description_consistency: float, regularity: float, amount_stability: float
) -> bool:
    if _LLM_LOW <= confidence < _LLM_HIGH:
        return True
    if (
        description_consistency < _DESC_VARIANCE_THRESHOLD
        and regularity >= _STABILITY_OK
        and amount_stability >= _STABILITY_OK
    ):
        return True
    return False


def _call_gemini(prompt: str) -> dict:
    client = gemini_client()
    response = client.models.generate_content(
        model=_MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = (response.text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _serialize_rule_for_prompt(r: RecurringRule) -> dict:
    return {
        "keyword": r.keyword,
        "normalized_key_pattern": r.normalized_key_pattern,
        "amount_median": r.amount_median,
        "frequency": r.frequency,
        "direction": r.direction,
    }


def llm_refine_cluster(
    *,
    cluster: CandidateCluster,
    frequency: Frequency,
    direction: Direction,
    heuristic_confidence: float,
    few_shot_rules: List[RecurringRule],
    user_id: UUID,
) -> Optional[RecurringRule]:
    prompt = _PROMPT_TEMPLATE.format(
        few_shot=json.dumps([_serialize_rule_for_prompt(r) for r in few_shot_rules[:20]], indent=2),
        descriptions=json.dumps(cluster.descriptions[:20]),
        amounts=json.dumps(cluster.amounts[:20]),
        heuristic=round(heuristic_confidence, 2),
    )
    try:
        payload = _call_gemini(prompt)
    except Exception:  # noqa: BLE001
        logger.exception("LLM tiebreaker failed; falling back to heuristic")
        return None

    abs_amts = [abs(a) for a in cluster.amounts]
    median_amt = statistics.median(abs_amts)
    return RecurringRule(
        user_id=user_id,
        keyword=payload["keyword"],
        normalized_key_pattern=payload["normalized_key_pattern"],
        amount_min=min(abs_amts),
        amount_max=max(abs_amts),
        amount_median=median_amt,
        frequency=frequency,
        direction=direction,
        confidence=float(payload.get("confidence", heuristic_confidence)),
        status=Status.PENDING_REVIEW,
        source=Source.LLM,
        occurrences_observed=len(cluster.transaction_ids),
        sample_transaction_ids=[],
    )
