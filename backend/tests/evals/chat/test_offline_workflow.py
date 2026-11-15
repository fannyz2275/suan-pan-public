import json

import pytest

from tests.evals.chat.offline_control import WEIGHTS


def scenario(name="q1"):
    return {"id": name, "fixture": {"metrics": {"cash": 12000, "expenses": 3000}},
            "turns": [{"question": "Cash?", "expected": {"cash": 12000}},
                      {"question": "Expenses?", "expected": {"expenses": 3000}},
                      {"question": "Explain briefly", "expected": {}}],
            "budgets": {"cost": {"target": .1, "upper": .3},
                        "latency": {"target": 10, "upper": 60},
                        "tools": {"target": 3, "upper": 10}}}


def good_executor(scenario, setup, transport, question_id, call_prefix):
    return {"scores": dict.fromkeys(WEIGHTS, 1.0), "hard_failures": [],
            "turns": [{"question": t["question"], "answer": "answer", "scores": {}}
                      for t in scenario["turns"]], "telemetry": {}, "memory_events": []}


def test_cli_reads_only_explicit_local_key_file(tmp_path, monkeypatch):
    from tests.evals.chat import offline_workflow, openrouter_transport
    path = tmp_path / "run"
    offline_workflow.Workflow.create(path, {"split": "development", "scenarios": [scenario()]}, {})
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=test-local-secret\nUNRELATED_SECRET=not-exported\n")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    seen = []
    monkeypatch.setattr(openrouter_transport, "OpenRouterTransport", lambda ledger, key: seen.append(key))
    monkeypatch.setattr(offline_workflow.Workflow, "step", lambda self, transport: {"status": "test"})
    assert offline_workflow.main(["step", "--run-dir", str(path), "--env-file", str(env)]) == 0
    assert seen == ["test-local-secret"]
    assert "test-local-secret" not in (path / "manifest.json").read_text()


def test_cli_workflow_three_rounds_resume_and_carry_setup(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    path = tmp_path / "run"
    Workflow.create(path, {"split": "development", "scenarios": [scenario(), scenario("q2")]}, {})
    with Workflow(path, executor=good_executor) as flow:
        assert flow.step(None)["status"] == "awaiting_update"
        flow.update({"response_prompt": "Be brief"}, "Too long", ["q1/1"])
    with Workflow(path, executor=good_executor) as flow:
        assert flow.step(None)["status"] == "awaiting_update"
        flow.update({"response_prompt": "Be brief"}, "No change justified", ["q1/1"])
        assert flow.step(None)["status"] == "conversation_complete"
        flow.step(None)
        report = flow.report()
        assert report["questions"][1]["initial_setup"]["response_prompt"] == "Be brief"
        assert len(report["questions"][0]["rounds"]) == 3
        assert len(report["questions"][0]["updates"]) == 2
        assert (path / "report.md").exists()
        assert (path / "final-setup.json").exists()


def test_rejected_candidate_consumes_update_slot(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {})
    with Workflow(tmp_path / "run", executor=good_executor) as flow:
        flow.step(None)
        flow.update({"model": "unauthorized"}, "Try change", ["q1/1"])
        assert flow.report()["questions"][0]["updates"][0]["retained"] is False
        assert flow.step(None)["status"] == "awaiting_update"


def test_report_latency_percentiles_are_separated_by_role_and_phase(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    def measured(*args):
        result = good_executor(*args)
        result["call_records"] = [
            {"role": "advisor", "latency_seconds": value} for value in (1, 3, 5)
        ] + [{"role": "memory", "latency_seconds": 20}]
        return result

    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {})
    with Workflow(tmp_path / "run", executor=measured) as flow:
        flow.step(None)
        stats = flow.report()["call_latency_seconds"]
        assert stats["development"]["advisor"] == {"count": 3, "p50": 3, "p95": 5}
        assert stats["development"]["memory"]["p50"] == 20
        assert stats["development"]["judge"]["p95"] is None
        assert stats["baseline"]["advisor"]["count"] == 0


def test_same_dataset_cannot_reset_budget_by_reinit(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    data = {"split": "development", "scenarios": [scenario()]}
    Workflow.create(tmp_path / "run", data, {})
    with pytest.raises(FileExistsError):
        Workflow.create(tmp_path / "run", data, {})


def test_holdout_rejects_updates_and_records_baseline_final_pair(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    Workflow.create(tmp_path / "run", {"split": "holdout", "scenarios": [scenario()]},
                    {}, candidate={"response_prompt": "Candidate"})
    with Workflow(tmp_path / "run", executor=good_executor) as flow:
        with pytest.raises(ValueError, match="holdout"):
            flow.update({}, "leak", ["q1/1"])
        flow.replay(None)
        flow.replay(None)
        report = flow.report()
        assert len(report["questions"][0]["replays"]) == 2
        assert report["paired_comparison"]["mean_delta"] == 0
        assert report["paired_comparison"]["sample_count"] == 1


def test_failed_candidate_round_is_reverted_and_reason_exported(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    def executor(*args):
        result = good_executor(*args)
        if args[1]["response_prompt"] == "Bad candidate":
            result["hard_failures"] = ["wrong_number"]
        return result

    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {})
    with Workflow(tmp_path / "run", executor=executor) as flow:
        flow.step(None)
        flow.update({"response_prompt": "Bad candidate"}, "hypothesis", ["q1/1"])
        flow.step(None)
        q = flow.report()["questions"][0]
        assert q["updates"][0]["retained"] is False
        assert "wrong_number" in q["updates"][0]["rollback_reason"]


def test_dataset_contains_no_duplicate_ids_or_holdout_training_mix(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    with pytest.raises(ValueError):
        Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario(), scenario()]}, {})


def test_report_gate_fails_for_bad_holdout_even_with_positive_delta(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    def bad(*args):
        result = good_executor(*args)
        result["hard_failures"] = ["wrong_number"]
        return result

    Workflow.create(tmp_path / "run", {"split": "holdout", "scenarios": [scenario()]}, {}, candidate={})
    with Workflow(tmp_path / "run", executor=bad) as flow:
        flow.replay(None)
        flow.replay(None)
        assert flow.report()["gate"]["passed"] is False


def test_cli_report_no_secrets_or_provider_needed(tmp_path, capsys):
    from tests.evals.chat.offline_workflow import Workflow, main

    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {})
    assert main(["report", "--run-dir", str(tmp_path / "run")]) == 0
    assert "report.md" in capsys.readouterr().out


def test_unknown_transport_outcome_is_not_retried_by_step(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow
    from tests.evals.chat.offline_control import PendingCall

    def broken(scenario, setup, transport, qid, prefix):
        transport.reserve(qid, prefix + "/call", 10)
        raise TimeoutError()

    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {})
    with Workflow(tmp_path / "run", executor=broken) as flow:
        with pytest.raises(TimeoutError):
            flow.step(flow.ledger)
        with pytest.raises(PendingCall):
            flow.step(flow.ledger)
        assert flow.report()["questions"][0]["reserved_microusd"] == 10


def test_nonnumeric_deterministic_tool_regression_rejects_candidate(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    tool = {"name": "coverage", "description": "Months of cash", "expression": "cash / expenses",
            "tests": [{"metrics": {"cash": 12000, "expenses": 3000}, "expected": 4}]}
    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {"tools": [tool]})
    with Workflow(tmp_path / "run", executor=good_executor) as flow:
        flow.step(None)
        bad_tool = {**tool, "expression": "cash * expenses", "tests": [
            {"metrics": {"cash": 1, "expenses": 1}, "expected": 1}]}
        result = flow.update({"tools": [bad_tool]}, "try formula", ["q1/1"])
        assert result["retained"] is False


def test_two_updates_cannot_weaken_tool_oracle_then_break_formula(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow

    tool = {"name": "coverage", "description": "Months", "expression": "cash / expenses",
            "tests": [{"metrics": {"cash": 12000, "expenses": 3000}, "expected": 4}]}
    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {"tools": [tool]})
    with Workflow(tmp_path / "run", executor=good_executor) as flow:
        flow.step(None)
        weak = {**tool, "tests": [{"metrics": {"cash": 1, "expenses": 1}, "expected": 1}]}
        assert flow.update({"tools": [weak]}, "New tests", ["q1/1"])["retained"]
        flow.step(None)
        assert not flow.update({"tools": [{**weak, "expression": "cash * expenses"}]},
                               "New formula", ["q1/1"])["retained"]


def test_stopped_unverified_candidate_does_not_carry_to_next_question(tmp_path):
    from tests.evals.chat.offline_workflow import Workflow
    from tests.evals.chat.offline_control import BudgetExceeded

    def executor(scenario, setup, transport, qid, prefix):
        if setup["response_prompt"] == "Unverified":
            transport.reserve(qid, prefix + "/too-big", 1_000_001)
        return good_executor(scenario, setup, transport, qid, prefix)

    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario(), scenario("q2")]}, {})
    with Workflow(tmp_path / "run", executor=executor) as flow:
        flow.step(flow.ledger)
        flow.update({"response_prompt": "Unverified"}, "hypothesis", ["q1/1"])
        with pytest.raises(BudgetExceeded):
            flow.step(flow.ledger)
        flow.step(flow.ledger)
        assert flow.report()["questions"][1]["initial_setup"]["response_prompt"] != "Unverified"


def test_resume_refuses_changed_harness_code(tmp_path, monkeypatch):
    from tests.evals.chat import offline_workflow as module

    module.Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {})
    monkeypatch.setattr(module, "runtime_hash", lambda: "different")
    with pytest.raises(ValueError, match="changed"):
        with module.Workflow(tmp_path / "run"):
            pass


def test_real_executor_transport_and_ledger_run_all_rounds_without_network(tmp_path):
    import httpx
    from tests.evals.chat.offline_workflow import Workflow
    from tests.evals.chat.openrouter_transport import OpenRouterTransport

    requests = []
    def serve(request):
        body = json.loads(request.content)
        requests.append(body)
        if body["model"] == "google/gemini-2.5-flash":
            payload = json.loads(body["messages"][-1]["content"])
            answer = payload["answer"]
            claims = []
            for key, value in (("cash", 12000), ("expenses", 3000)):
                if str(value) in answer:
                    claims.append({"metric_key": key, "value": value, "quote": str(value)})
            message = {"role": "assistant", "content": json.dumps(
                {"directness": 100, "concision": 100, "claims": claims})}
        else:
            question = next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user")
            if question == "Cash?" and body["messages"][-1]["role"] != "tool":
                message = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "lookup", "type": "function", "function": {"name": "get_metrics", "arguments": "{}"}}]}
            else:
                message = {"role": "assistant", "content": {"Cash?": "12000", "Expenses?": "3000"}.get(question, "Kept brief.")}
        return httpx.Response(200, json={"model": body["model"], "provider": "mock",
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "cost": .0001}})

    Workflow.create(tmp_path / "run", {"split": "development", "scenarios": [scenario()]}, {})
    with Workflow(tmp_path / "run") as flow, httpx.Client(transport=httpx.MockTransport(serve)) as client:
        transport = OpenRouterTransport(flow.ledger, "mock-key", client=client)
        for round_number in range(3):
            flow.step(transport)
            if round_number < 2:
                flow.update({}, "No-op repeatability check", ["q1/1"])
        report = flow.report()
        assert len(report["questions"][0]["rounds"]) == 3
        assert all(r["passed"] for r in report["questions"][0]["rounds"])
        assert report["questions"][0]["rounds"][0]["details"]["call_records"][0]["model"] == "deepseek/deepseek-v3.2"
        assert report["questions"][0]["spent_microusd"] == len(requests) * 100
        flow.replay(transport)
        flow.replay(transport)
        assert flow.report()["gate"]["passed"]
