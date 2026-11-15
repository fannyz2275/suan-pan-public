from unittest.mock import patch
from uuid import uuid4

import pytest

from app.engine.recurring.cluster import CandidateCluster
from app.engine.recurring.llm import llm_refine_cluster, should_use_llm
from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)


def _cluster():
    return CandidateCluster(
        normalized_key="con ed electric",
        transaction_ids=["t1", "t2", "t3"],
        descriptions=["CON ED ELECTRIC BILL", "CON EDISON CO", "CON ED"],
        amounts=[-95.50, -110.25, -88.00],
        dates=[],
    )


def _rule():
    return RecurringRule(
        user_id=uuid4(),
        keyword="Con Edison Electric",
        normalized_key_pattern="con edison electric",
        amount_min=80.0, amount_max=130.0, amount_median=100.0,
        frequency=Frequency.MONTHLY, direction=Direction.EXPENSE,
        confidence=1.0, status=Status.USER_CONFIRMED, source=Source.USER_CREATED,
    )


def test_should_use_llm_mid_confidence():
    assert should_use_llm(confidence=0.55, description_consistency=0.9, regularity=0.9, amount_stability=0.9)


def test_should_use_llm_inconsistent_descriptions_but_stable():
    assert should_use_llm(confidence=0.82, description_consistency=0.3, regularity=0.9, amount_stability=0.85)


def test_should_not_use_llm_for_high_confidence_consistent():
    assert not should_use_llm(confidence=0.9, description_consistency=0.9, regularity=0.9, amount_stability=0.9)


def test_should_not_use_llm_for_low_confidence():
    assert not should_use_llm(confidence=0.2, description_consistency=0.5, regularity=0.5, amount_stability=0.5)


def test_llm_refine_returns_rule_matching_schema():
    fake_response = {
        "keyword": "Con Edison Electric",
        "normalized_key_pattern": "con edison",
        "confidence": 0.8,
    }
    with patch("app.engine.recurring.llm._call_gemini", return_value=fake_response):
        rule = llm_refine_cluster(
            cluster=_cluster(),
            frequency=Frequency.MONTHLY,
            direction=Direction.EXPENSE,
            heuristic_confidence=0.6,
            few_shot_rules=[_rule()],
            user_id=uuid4(),
        )
    assert rule.keyword == "Con Edison Electric"
    assert rule.source == Source.LLM
    assert rule.confidence == 0.8


def test_llm_failure_returns_none():
    with patch("app.engine.recurring.llm._call_gemini", side_effect=RuntimeError("API down")):
        result = llm_refine_cluster(
            cluster=_cluster(),
            frequency=Frequency.MONTHLY,
            direction=Direction.EXPENSE,
            heuristic_confidence=0.6,
            few_shot_rules=[],
            user_id=uuid4(),
        )
    assert result is None
