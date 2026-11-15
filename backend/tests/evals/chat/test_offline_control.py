"""Offline controls never load application settings or contact a provider."""
import pytest


def test_weighted_scores_are_normalized_before_aggregation():
    from tests.evals.chat.offline_control import aggregate, normalize, efficiency

    scores = dict(accuracy=normalize(100), directness=normalize(80),
                  concision=normalize(50), cost=efficiency(2, 1, 3),
                  latency=1.0, tools=0.0)
    assert aggregate(scores) == pytest.approx(20.4 / 26)


@pytest.mark.parametrize("bad", [-1, 101, float("nan"), float("inf"), True])
def test_invalid_raw_score_fails_closed(bad):
    from tests.evals.chat.offline_control import normalize

    with pytest.raises(ValueError):
        normalize(bad)


def test_efficiency_boundaries_and_missing_metrics():
    from tests.evals.chat.offline_control import efficiency, aggregate

    assert efficiency(0, 2, 4) == 1
    assert efficiency(2, 2, 4) == 1
    assert efficiency(3, 2, 4) == .5
    assert efficiency(4, 2, 4) == 0
    with pytest.raises(ValueError):
        efficiency(1, 2, 2)
    with pytest.raises(ValueError):
        aggregate({"accuracy": 1})


def test_numeric_failure_cannot_be_hidden_by_perfect_score():
    from tests.evals.chat.offline_control import passes, WEIGHTS

    scores = dict.fromkeys(WEIGHTS, 1.0)
    assert passes(scores, [])
    assert not passes(scores, ["wrong_date_range"])


def test_budget_is_shared_across_rounds_and_survives_restart(tmp_path):
    from tests.evals.chat.offline_control import Ledger, BudgetExceeded

    path = tmp_path / "run.sqlite"
    with Ledger(path) as ledger:
        ledger.add_question("q1", {"prompt": "v1"})
        ledger.start_round("q1")
        ledger.reserve("q1", "advisor-1", 600_000)
        ledger.settle("advisor-1", 400_000, {"text": "answer"})
    with Ledger(path) as ledger:
        ledger.add_question("q1", {"prompt": "v1"})
        assert ledger.summary("q1")["remaining_microusd"] == 600_000
        with pytest.raises(BudgetExceeded):
            ledger.reserve("q1", "judge-1", 600_001)
        assert ledger.summary("q1")["remaining_microusd"] == 600_000


def test_pending_calls_block_resume_and_duplicate_calls_are_not_reissued(tmp_path):
    from tests.evals.chat.offline_control import Ledger, PendingCall, InvalidTransition

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        ledger.reserve("q", "call", 200_000)
        with pytest.raises(PendingCall):
            ledger.reserve("q", "another", 100_000)
        with pytest.raises(PendingCall):
            ledger.reserve("q", "call", 200_000)
        ledger.settle("call", 100_000, {"text": "persisted"})
        assert ledger.cached("call") == {"text": "persisted"}
        with pytest.raises(InvalidTransition):
            ledger.reserve("q", "call", 200_000)


def test_three_rounds_two_updates_and_complete_trajectory(tmp_path):
    from tests.evals.chat.offline_control import Ledger, InvalidTransition, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {"prompt": "v1"})
        for round_number in range(1, 4):
            assert ledger.start_round("q") == round_number
            ledger.finish_round("q", dict.fromkeys(WEIGHTS, .9), [],
                                [{"question": "Why?", "answer": "Evidence"}])
            if round_number < 3:
                ledger.apply_update("q", {"prompt": f"v{round_number + 1}"},
                                    "Answer buried", ["q/turn-1"], "Prompt changed", True)
        report = ledger.summary("q")
        assert len(report["rounds"]) == 3
        assert len(report["updates"]) == 2
        assert report["setup"] == {"prompt": "v3"}
        assert report["updates"][0]["trigger_cases"] == ["q/turn-1"]
        with pytest.raises(InvalidTransition):
            ledger.start_round("q")
        with pytest.raises(InvalidTransition):
            ledger.apply_update("q", {}, "extra", ["q/turn-1"], "extra", True)


def test_rejected_patch_consumes_slot_without_changing_setup(tmp_path):
    from tests.evals.chat.offline_control import Ledger, InvalidTransition, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {"tools": "v1"})
        ledger.start_round("q")
        ledger.finish_round("q", dict.fromkeys(WEIGHTS, 1.0), [], [])
        ledger.apply_update("q", {"tools": "unsafe"}, "failed tool test",
                            ["q/turn-1"], "tool patch", False)
        assert ledger.summary("q")["setup"] == {"tools": "v1"}
        with pytest.raises(InvalidTransition):
            ledger.apply_update("q", {}, "retry", ["q/turn-1"], "patch", True)
        assert ledger.start_round("q") == 2


def test_pending_call_prevents_round_completion(tmp_path):
    from tests.evals.chat.offline_control import Ledger, PendingCall, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        ledger.reserve("q", "timeout", 300_000)
        with pytest.raises(PendingCall):
            ledger.finish_round("q", dict.fromkeys(WEIGHTS, 1.0), [], [])


def test_cannot_resettle_call_or_change_question_initial_setup(tmp_path):
    from tests.evals.chat.offline_control import Ledger, InvalidTransition

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        with pytest.raises(InvalidTransition):
            ledger.add_question("q", {"different": True})
        ledger.start_round("q")
        ledger.reserve("q", "call", 10)
        ledger.settle("call", 5, {})
        with pytest.raises(InvalidTransition):
            ledger.settle("call", 0, {})


def test_over_reservation_usage_is_recorded_and_blocks_more_calls(tmp_path):
    from tests.evals.chat.offline_control import Ledger, BudgetExceeded

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        ledger.reserve("q", "call", 10)
        with pytest.raises(BudgetExceeded):
            ledger.settle("call", 20, {})
        assert ledger.summary("q")["spent_microusd"] == 20
        with pytest.raises(BudgetExceeded):
            ledger.reserve("q", "next", 1)


def test_second_connection_sees_reservation_and_exact_cap_is_allowed(tmp_path):
    from tests.evals.chat.offline_control import Ledger, PendingCall, BudgetExceeded

    path = tmp_path / "run.sqlite"
    with Ledger(path) as first, Ledger(path) as second:
        first.add_question("q", {})
        first.start_round("q")
        first.reserve("q", "one-dollar", 1_000_000)
        assert second.summary("q")["remaining_microusd"] == 0
        with pytest.raises(PendingCall):
            second.reserve("q", "concurrent", 1)
        first.settle("one-dollar", 1_000_000, {})
        with pytest.raises(BudgetExceeded):
            second.reserve("q", "over-limit", 1)


def test_cannot_start_next_round_without_update_decision(tmp_path):
    from tests.evals.chat.offline_control import Ledger, InvalidTransition, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        ledger.finish_round("q", dict.fromkeys(WEIGHTS, 1.0), [], [])
        with pytest.raises(InvalidTransition):
            ledger.start_round("q")


def test_incomplete_transcript_cannot_pass(tmp_path):
    from tests.evals.chat.offline_control import Ledger, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        ledger.finish_round("q", dict.fromkeys(WEIGHTS, 1.0), [], [])
        report = ledger.summary("q")["rounds"][0]
        assert report["passed"] is False
        assert "incomplete_transcript" in report["hard_failures"]


def test_next_question_inherits_setup_not_spend_or_conversation(tmp_path):
    from tests.evals.chat.offline_control import Ledger, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q1", {"response": "old"})
        ledger.start_round("q1")
        ledger.reserve("q1", "q1-call", 500_000)
        ledger.settle("q1-call", 500_000, {})
        ledger.finish_round("q1", dict.fromkeys(WEIGHTS, 1.0), [], [])
        ledger.apply_update("q1", {"response": "new"}, "simplify", ["q1/1"], "diff", True)
        ledger.add_question("q2", ledger.summary("q1")["setup"])
        second = ledger.summary("q2")
        assert second["setup"] == {"response": "new"}
        assert second["rounds"] == []
        assert second["remaining_microusd"] == 1_000_000


def test_budget_denial_is_terminal_even_with_smaller_retry_after_restart(tmp_path):
    from tests.evals.chat.offline_control import Ledger, BudgetExceeded

    path = tmp_path / "run.sqlite"
    with Ledger(path) as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        with pytest.raises(BudgetExceeded):
            ledger.reserve("q", "too-expensive", 1_000_001)
    with Ledger(path) as ledger:
        assert ledger.summary("q")["stop_reason"] == "budget_exhausted"
        with pytest.raises(BudgetExceeded):
            ledger.reserve("q", "cheaper-retry", 1)
        with pytest.raises(BudgetExceeded):
            ledger.start_round("q")


def test_dispatch_never_calls_provider_after_budget_stop(tmp_path):
    from tests.evals.chat.offline_control import Ledger, BudgetExceeded

    dispatched = []
    def provider():
        dispatched.append(True)
        return 100, {"answer": "test"}

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        with pytest.raises(BudgetExceeded):
            ledger.dispatch("q", "blocked", 1_000_001, provider)
        assert dispatched == []


def test_dispatch_records_success_and_timeout_stays_reserved(tmp_path):
    from tests.evals.chat.offline_control import Ledger, PendingCall

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        result = ledger.dispatch("q", "ok", 200, lambda: (100, {"answer": "saved"}))
        assert result == ledger.cached("ok") == {"answer": "saved"}
        def timeout():
            raise TimeoutError("Outcome unknown")
        with pytest.raises(TimeoutError):
            ledger.dispatch("q", "unknown", 200, timeout)
        with pytest.raises(PendingCall):
            ledger.dispatch("q", "retry", 200, lambda: (100, {}))
        assert ledger.summary("q")["reserved_microusd"] == 200


def test_exact_cap_blocks_updates_but_preserves_partial_report(tmp_path):
    from tests.evals.chat.offline_control import Ledger, BudgetExceeded, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_round("q")
        ledger.dispatch("q", "all", 1_000_000, lambda: (1_000_000, {}))
        ledger.finish_round("q", dict.fromkeys(WEIGHTS, 1.0), [],
                            [{"question": "Q", "answer": "A"}])
        assert ledger.summary("q")["rounds"][0]["passed"] is False
        with pytest.raises(BudgetExceeded):
            ledger.apply_update("q", {}, "try again", ["q/1"], "no-op", True)


def test_frozen_replay_shares_budget_and_cannot_be_repeated(tmp_path):
    from tests.evals.chat.offline_control import Ledger, InvalidTransition, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {})
        ledger.start_replay("q", "baseline")
        ledger.dispatch("q", "replay-call", 500_000, lambda: (400_000, {}))
        ledger.finish_replay("q", {"scores": dict.fromkeys(WEIGHTS, 1), "hard_failures": []})
        assert ledger.summary("q")["remaining_microusd"] == 600_000
        with pytest.raises(InvalidTransition):
            ledger.start_replay("q", "baseline")


def test_failed_updated_round_rolls_back_to_previous_setup(tmp_path):
    from tests.evals.chat.offline_control import Ledger, WEIGHTS

    with Ledger(tmp_path / "run.sqlite") as ledger:
        ledger.add_question("q", {"response": "old"})
        ledger.start_round("q")
        ledger.finish_round("q", dict.fromkeys(WEIGHTS, 1), [], [{"question": "q", "answer": "a"}])
        ledger.apply_update("q", {"response": "new"}, "reason", ["q/1"], "diff", True)
        ledger.start_round("q")
        ledger.finish_round("q", dict.fromkeys(WEIGHTS, .5), ["wrong_number"],
                            [{"question": "q", "answer": "wrong"}], {"telemetry": {"calls": 1}})
        ledger.rollback_update("q", "hard gate failed")
        assert ledger.summary("q")["setup"] == {"response": "old"}
        assert ledger.summary("q")["updates"][0]["retained"] is False
