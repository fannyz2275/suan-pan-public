"""Tests for the judge module."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

RUBRICS_PATH = Path(__file__).parent / "rubrics.yaml"


def _fake_resp(text: str) -> MagicMock:
    """google.genai's GenerateContentResponse exposes .text on the top-level resp."""
    resp = MagicMock()
    resp.text = text
    return resp


def test_load_rubric_returns_dict():
    from tests.evals.chat.judge import load_rubric
    r = load_rubric("portfolio_attribution_v1", RUBRICS_PATH)
    assert r["judge_model"] == "gemini-2.5-pro"
    assert r["judge_temperature"] == 0
    assert "judge_system_prompt" in r
    assert {c["id"] for c in r["criteria"]} == {
        "one_sentence_per_bucket",
        "flags_unattributed_when_over_100",
        "cites_concrete_number",
        "no_aggregate_paragraph",
    }


def test_load_rubric_unknown_id_raises():
    from tests.evals.chat.judge import load_rubric, RubricNotFound
    with pytest.raises(RubricNotFound):
        load_rubric("does-not-exist", RUBRICS_PATH)


def test_score_reply_parses_judge_json():
    from tests.evals.chat.judge import score_reply, load_rubric
    rubric = load_rubric("portfolio_attribution_v1", RUBRICS_PATH)

    fake = _fake_resp(
        '{"one_sentence_per_bucket": 0.9, "flags_unattributed_when_over_100": 1.0, '
        '"cites_concrete_number": 1.0, "no_aggregate_paragraph": 0.8}'
    )
    with patch("tests.evals.chat.judge._gemini_client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = fake
        scores = score_reply(
            rubric=rubric,
            user_messages=[{"role": "user", "content": "Why did my portfolio move?"}],
            advisor_reply="Market gained $1,200; contributions added $500.",
            tool_calls=[{"name": "portfolio_get_attribution", "args": {}, "result_data": {}}],
        )
    assert scores == {
        "one_sentence_per_bucket": 0.9,
        "flags_unattributed_when_over_100": 1.0,
        "cites_concrete_number": 1.0,
        "no_aggregate_paragraph": 0.8,
    }


def test_score_reply_malformed_json_raises():
    from tests.evals.chat.judge import score_reply, load_rubric, JudgeMalformedJSON
    rubric = load_rubric("portfolio_attribution_v1", RUBRICS_PATH)

    fake = _fake_resp("this is not JSON at all")
    with patch("tests.evals.chat.judge._gemini_client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = fake
        with pytest.raises(JudgeMalformedJSON):
            score_reply(
                rubric=rubric,
                user_messages=[{"role": "user", "content": "x"}],
                advisor_reply="x",
                tool_calls=[],
            )


def test_score_reply_judge_5xx_raises_unreachable():
    from tests.evals.chat.judge import score_reply, load_rubric, JudgeUnreachable
    from google.genai import errors as genai_errors

    rubric = load_rubric("portfolio_attribution_v1", RUBRICS_PATH)
    with patch("tests.evals.chat.judge._gemini_client") as mock_client:
        mock_client.return_value.models.generate_content.side_effect = (
            genai_errors.APIError(503, {"error": {"message": "transient"}})
        )
        with pytest.raises(JudgeUnreachable):
            score_reply(
                rubric=rubric,
                user_messages=[{"role": "user", "content": "x"}],
                advisor_reply="x",
                tool_calls=[],
            )


def test_check_forbidden_signals_returns_true_on_hit():
    from tests.evals.chat.judge import check_forbidden_signals

    fake = _fake_resp('{"hit": true}')
    with patch("tests.evals.chat.judge._gemini_client") as mock_client:
        mock_client.return_value.models.generate_content.return_value = fake
        hit = check_forbidden_signals(
            advisor_reply="I executed the trade for you.",
            forbidden_signals=["claims_to_execute_trade"],
            judge_model="gemini-2.5-pro",
        )
    assert hit is True


def test_check_forbidden_signals_returns_false_when_empty():
    from tests.evals.chat.judge import check_forbidden_signals
    # No forbidden signals -> never call Gemini.
    hit = check_forbidden_signals(
        advisor_reply="anything",
        forbidden_signals=[],
        judge_model="gemini-2.5-pro",
    )
    assert hit is False


def test_match_check_exact_tool_name_passes():
    from tests.evals.chat.judge import match_check
    actual = [{"name": "list_transactions", "args": {"date_from": "2026-04-01"}}]
    expected = [{"name": "list_transactions", "args_must_contain": {}}]
    assert match_check(actual, expected) is True


def test_match_check_missing_tool_fails():
    from tests.evals.chat.judge import match_check
    actual = [{"name": "get_recurring_rules", "args": {}}]
    expected = [{"name": "list_transactions", "args_must_contain": {}}]
    assert match_check(actual, expected) is False


def test_match_check_wildcard_arg_passes_when_present():
    from tests.evals.chat.judge import match_check
    actual = [{"name": "portfolio_get_attribution",
               "args": {"from_date": "2026-04-01", "to_date": "2026-05-01"}}]
    expected = [{"name": "portfolio_get_attribution",
                 "args_must_contain": {"from_date": "*", "to_date": "*"}}]
    assert match_check(actual, expected) is True


def test_match_check_wildcard_arg_fails_when_absent():
    from tests.evals.chat.judge import match_check
    actual = [{"name": "portfolio_get_attribution", "args": {}}]
    expected = [{"name": "portfolio_get_attribution",
                 "args_must_contain": {"from_date": "*"}}]
    assert match_check(actual, expected) is False


def test_match_check_explicit_arg_value_must_match():
    from tests.evals.chat.judge import match_check
    actual = [{"name": "portfolio_get_exposure", "args": {"dimension": "sector"}}]
    expected = [{"name": "portfolio_get_exposure",
                 "args_must_contain": {"dimension": "asset_class"}}]
    assert match_check(actual, expected) is False


def test_forbidden_check_returns_true_when_no_forbidden_called():
    from tests.evals.chat.judge import forbidden_check
    actual = [{"name": "list_transactions", "args": {}}]
    forbidden = ["execute_trade", "delete_account"]
    assert forbidden_check(actual, forbidden) is True


def test_forbidden_check_returns_false_when_forbidden_called():
    from tests.evals.chat.judge import forbidden_check
    actual = [{"name": "execute_trade", "args": {}}]
    forbidden = ["execute_trade"]
    assert forbidden_check(actual, forbidden) is False
