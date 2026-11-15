"""End-to-end integration test for run_eval with mocked external clients."""
from unittest.mock import MagicMock, patch


def test_legacy_cli_refuses_unbudgeted_live_calls(capsys):
    from tests.evals.chat.run_eval import main

    with patch("tests.evals.chat.run_eval.run_one_scenario") as run:
        assert main(["--limit", "1"]) == 2
        run.assert_not_called()
    assert "disabled" in capsys.readouterr().err.lower()


def test_dry_run_validates_dataset_without_calling_anything(tmp_path, capsys):
    from tests.evals.chat.run_eval import main
    rc = main(["--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "valid" in out.lower()


def test_run_with_one_scenario_produces_scored_record():
    """Drive the loop with mocked ChatSession + mocked judge.

    The scenario's expected_tools matches the mocked tool calls and the
    mocked judge returns 1.0 on every criterion, so the run should pass 3/3.
    """
    from tests.evals.chat.run_eval import run_one_scenario

    scenario = {
        "id": "test.smoke",
        "tags": ["test"],
        "setup": {"seed_id": "single_account_2_holdings", "fred_mock": None, "extra_sql": None},
        "messages": [{"role": "user", "content": "test?"}],
        "expected_tools": [{"name": "portfolio_get_attribution", "args_must_contain": {}}],
        "forbidden_tools": [],
        "expected_signals": [
            {"id": "one_sentence_per_bucket", "weight": 0.3, "required": True},
            {"id": "flags_unattributed_when_over_100", "weight": 0.3, "required": True},
            {"id": "cites_concrete_number", "weight": 0.2, "required": True},
            {"id": "no_aggregate_paragraph", "weight": 0.2, "required": False},
        ],
        "forbidden_signals": [],
        "judge_prompt_id": "portfolio_attribution_v1",
        "n_runs": 3,
        "pass_threshold": 0.8,
    }

    fake_session = MagicMock()
    fake_session.send.return_value = (
        "Market gained $1,200; contributions added $500.",
        [{"name": "portfolio_get_attribution", "args": {}, "result_data": {"unattributed": 0}}],
    )
    fake_judge_scores = {
        "one_sentence_per_bucket": 1.0,
        "flags_unattributed_when_over_100": 1.0,
        "cites_concrete_number": 1.0,
        "no_aggregate_paragraph": 1.0,
    }

    with patch("tests.evals.chat.run_eval._make_chat_session", return_value=fake_session), \
         patch("tests.evals.chat.run_eval._apply_seed", return_value=None), \
         patch("tests.evals.chat.run_eval.score_reply", return_value=fake_judge_scores), \
         patch("tests.evals.chat.run_eval.check_forbidden_signals", return_value=False):
        result = run_one_scenario(scenario)

    assert len(result["runs"]) == 3
    assert all(r["score"] == 1.0 for r in result["runs"])
    assert result["scenario_pass"] is True
    assert "[FLAKY]" not in [t for r in result["runs"] for t in r["tags"]]


def test_run_with_failing_required_criterion_marks_run_failed():
    from tests.evals.chat.run_eval import run_one_scenario

    scenario = {
        "id": "test.fail",
        "tags": ["test"],
        "setup": {"seed_id": "single_account_2_holdings", "fred_mock": None, "extra_sql": None},
        "messages": [{"role": "user", "content": "test?"}],
        "expected_tools": [{"name": "portfolio_get_attribution", "args_must_contain": {}}],
        "forbidden_tools": [],
        "expected_signals": [
            {"id": "one_sentence_per_bucket", "weight": 0.5, "required": True},
            {"id": "cites_concrete_number", "weight": 0.5, "required": False},
        ],
        "forbidden_signals": [],
        "judge_prompt_id": "portfolio_attribution_v1",
        "n_runs": 3,
        "pass_threshold": 0.8,
    }

    fake_session = MagicMock()
    fake_session.send.return_value = (
        "vague reply",
        [{"name": "portfolio_get_attribution", "args": {}, "result_data": {}}],
    )
    bad_scores = {"one_sentence_per_bucket": 0.0, "cites_concrete_number": 1.0}

    with patch("tests.evals.chat.run_eval._make_chat_session", return_value=fake_session), \
         patch("tests.evals.chat.run_eval._apply_seed", return_value=None), \
         patch("tests.evals.chat.run_eval.score_reply", return_value=bad_scores), \
         patch("tests.evals.chat.run_eval.check_forbidden_signals", return_value=False):
        result = run_one_scenario(scenario)

    assert all(r["score"] == 0.0 for r in result["runs"])
    assert result["scenario_pass"] is False


def test_run_with_tool_miss_marks_tool_miss_tag():
    from tests.evals.chat.run_eval import run_one_scenario

    scenario = {
        "id": "test.tool_miss",
        "tags": ["test"],
        "setup": {"seed_id": "single_account_2_holdings", "fred_mock": None, "extra_sql": None},
        "messages": [{"role": "user", "content": "test?"}],
        "expected_tools": [{"name": "portfolio_get_attribution", "args_must_contain": {}}],
        "forbidden_tools": [],
        "expected_signals": [
            {"id": "cites_concrete_number", "weight": 1.0, "required": True},
        ],
        "forbidden_signals": [],
        "judge_prompt_id": "portfolio_attribution_v1",
        "n_runs": 3,
        "pass_threshold": 0.8,
    }

    fake_session = MagicMock()
    fake_session.send.return_value = ("reply", [{"name": "list_transactions", "args": {}}])

    with patch("tests.evals.chat.run_eval._make_chat_session", return_value=fake_session), \
         patch("tests.evals.chat.run_eval._apply_seed", return_value=None), \
         patch("tests.evals.chat.run_eval.score_reply") as mock_score, \
         patch("tests.evals.chat.run_eval.check_forbidden_signals", return_value=False):
        result = run_one_scenario(scenario)

    mock_score.assert_not_called()
    assert all("[TOOL-MISS]" in r["tags"] for r in result["runs"])
    assert all(r["score"] == 0.0 for r in result["runs"])
