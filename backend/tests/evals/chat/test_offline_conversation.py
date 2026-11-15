import json

import pytest

from .offline_conversation import evaluate_expression, run_conversation, validate_setup


class Transport:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, qid, callid, role, messages, **kwargs):
        self.calls.append((role, messages, kwargs))
        reply = next(self.replies)
        return {"choices": [{"message": reply}], "_telemetry": {
            "cost_microusd": 100, "latency_seconds": .1}}


def scenario():
    return {"id": "s", "fixture": {"metrics": {"cash": 100}}, "turns": [
        {"question": "What is my cash?", "expected": {"cash": 100}}],
        "budgets": {key: {"target": 1, "upper": 10}
                    for key in ("cost", "latency", "tools")}}


def judge(value=100, quote="$100"):
    return {"content": json.dumps({"directness": 100, "concision": 100,
        "claims": [{"metric_key": "cash", "value": value, "quote": quote}]})}


def test_correct_and_oracle_hidden():
    transport = Transport([{"content": "You have $100."}, judge()])
    result = run_conversation(scenario(), {}, transport, "q", "run")
    assert result["scores"]["accuracy"] == 1
    assert result["hard_failures"] == []
    assert "expected" not in json.dumps(transport.calls[0])
    assert "100" not in json.dumps(transport.calls[0])


def test_v2_span_judge_integration():
    case = scenario()
    case['evaluation_version'] = 'spans-v2'
    case['turns'][0]['checks'] = {'grounded': 'Use evidence only'}
    transport = Transport([{'content': '1. **$100 cash**'}, {'content': json.dumps({
        'directness': 100, 'concision': 100, 'claims': [{'id': 0, 'keys': ['cash']}],
        'checks': {'grounded': {'passed': True, 'reason': 'Supported'}}})}])
    result = run_conversation(case, {}, transport, 'q', 'r')
    assert not result['hard_failures']
    assert result['turns'][0]['evaluator_errors'] == []


def test_null_optional_reasoning_is_not_replayed():
    transport = Transport([
        {"content": None, "reasoning": None, "reasoning_details": None,
         "tool_calls": [{"id": "t", "type": "function", "function": {
             "name": "get_metrics", "arguments": "{}"}}]},
        {"content": "$100"}, judge()])
    result = run_conversation(scenario(), {}, transport, "q", "r")
    assert not result["hard_failures"]
    assistant = transport.calls[1][1][2]
    assert "reasoning" not in assistant
    assert "reasoning_details" not in assistant


@pytest.mark.parametrize("extra,failed", [(50, False), (51, True)])
def test_optional_verified_claims(extra, failed):
    case = scenario()
    case["turns"][0]["references"] = {"income": 50}
    answer = f"$100 cash; ${extra} income."
    rating = {"directness": 100, "concision": 100, "claims": [
        {"metric_key": "cash", "value": 100, "quote": "$100"},
        {"metric_key": "income", "value": extra, "quote": f"${extra}"}]}
    result = run_conversation(case, {}, Transport([
        {"content": answer}, {"content": json.dumps(rating)}]), "q", "r")
    assert bool(result["hard_failures"]) is failed


def test_optional_claim_not_required_and_cannot_override_oracle():
    case = scenario()
    case["turns"][0]["references"] = {"income": 50, "cash": 999}
    result = run_conversation(case, {}, Transport([
        {"content": "$100"}, judge()]), "q", "r")
    assert result["hard_failures"] == []


@pytest.mark.parametrize("expression", ["__import__('os')", "cash**2", "cash.x", "cash[0]", "True", "1/0"])
def test_unsafe_expressions(expression):
    with pytest.raises(ValueError):
        evaluate_expression(expression, {"cash": 100})


def test_setup_override_rejected():
    with pytest.raises(ValueError):
        validate_setup({"model": "other"})


@pytest.mark.parametrize("answer,judgement", [
    ("You have $100.", judge(100, "$999")),
    ("I do not know.", judge(100, "I do not know.")),
    ("You have $99.", judge(99, "$99")),
    ("You have $100.", {"content": "bad JSON"}),
])
def test_false_success_rejected(answer, judgement):
    result = run_conversation(scenario(), {}, Transport([
        {"content": answer}, judgement]), "q", "run")
    assert result["scores"]["accuracy"] == 0
    assert result["hard_failures"]


def test_tool_trace_and_memory_isolation():
    case = scenario()
    case["acquisition"] = ["Please be brief."]
    case["turns"][0]["required_tools"] = ["get_metrics"]
    case["turns"][0]["expected_memory"] = {"detail": "brief"}
    transport = Transport([
        {"content": json.dumps({"updates": [{"key": "detail", "value": "brief", "quote": "Please be brief."},
            {"key": "cash", "value": 1, "quote": "Please be brief."}]})},
        {"content": None, "tool_calls": [{"id": "t", "type": "function", "function": {"name": "get_metrics", "arguments": "{}"}}]},
        {"content": "$100"}, judge(),
    ])
    result = run_conversation(case, {}, transport, "q", "run")
    assert result["turns"][0]["tool_trace"][0]["result"] == {"metrics": {"cash": 100}}
    advisor = json.dumps(transport.calls[1])
    assert "Please be brief." not in advisor
    assert 'brief' in advisor
    assert result["memory_events"][1]["accepted"] is False


def test_custom_tool_uses_fixture_not_its_self_tests():
    case = scenario()
    case["turns"][0]["expected"] = {"double_cash": 200}
    case["turns"][0]["required_tools"] = ["double_cash"]
    setup = {"tools": [{"name": "double_cash", "description": "Double cash",
        "expression": "cash * 2", "tests": [{"metrics": {"cash": 2}, "expected": 4}]}]}
    transport = Transport([
        {"tool_calls": [{"id": "t", "function": {"name": "double_cash", "arguments": "{}"}}]},
        {"content": "$200"}, {"content": json.dumps({"directness": 100, "concision": 100,
            "claims": [{"metric_key": "double_cash", "value": 200, "quote": "$200"}]})}])
    result = run_conversation(case, setup, transport, "q", "run")
    assert result["hard_failures"] == []
    assert result["turns"][0]["tool_trace"][0]["result"] == {"value": 200}


def test_transport_error_propagates():
    class Broken:
        def complete(self, *args, **kwargs):
            raise TimeoutError("unknown outcome")
    with pytest.raises(TimeoutError):
        run_conversation(scenario(), {}, Broken(), "q", "run")


def test_tool_limit_is_hard_failure():
    transport = Transport([
        {"tool_calls": [{"id": "t", "function": {"name": "get_metrics", "arguments": "{}"}}]},
        {"content": json.dumps({"directness": 0, "concision": 0, "claims": []})}])
    result = run_conversation(scenario(), {"effort": {"max_tool_calls": 0}}, transport, "q", "run")
    assert "turn_0:tool_limit_exceeded" in result["hard_failures"]


def test_nonnumeric_followup_and_role_costs():
    case = scenario()
    case["acquisition"] = ["Be brief"]
    case["fixture"]["scope"] = "household"
    case["turns"].append({"question": "Thanks", "expected": {}})
    transport = Transport([
        {"content": '{"updates":[]}'},
        {"content": "$100", "reasoning": "private", "refusal": None}, judge(),
        {"content": "You're welcome."},
        {"content": '{"directness":100,"concision":100,"claims":[]}'},
    ])
    result = run_conversation(case, {"effort": {"max_tokens": 100}}, transport, "q", "r")
    assert result["hard_failures"] == []
    assert result["telemetry"]["cost_microusd"] == 500
    assert result["telemetry"]["advisor_cost_microusd"] == 200
    assert result["telemetry"]["advisor_latency_seconds"] == pytest.approx(.2)
    assert transport.calls[0][2]["max_tokens"] == 1024
    assert transport.calls[2][2]["max_tokens"] == 1024
    final_judge = json.dumps(transport.calls[-1][1])
    assert "What is my cash?" in final_judge
    assert "refusal" not in json.dumps(transport.calls[3][1])
    assert "private" in json.dumps(transport.calls[3][1])
    assert "private" not in final_judge
    assert result["turns"][0]["judge_raw"]["directness"] == 100


def test_unextracted_numeric_claim_fails():
    result = run_conversation(scenario(), {}, Transport([
        {"content": "$100 cash and $500 income"}, judge()]), "q", "r")
    assert result["hard_failures"]
    assert result["scores"]["accuracy"] == 0


def test_memory_correction_deletion_and_capacity():
    case = scenario()
    case["acquisition"] = ["Brief then detailed. Forget detail. Use English."]
    updates = [{"key": key, "value": value, "op": op, "quote": "Brief then detailed. Forget detail. Use English."}
        for key, value, op in [("detail", "brief", "update"), ("detail", "detailed", "update"),
            ("language", "English", "update"), ("detail", "", "delete"), ("language", "English", "update")]]
    transport = Transport([{"content": json.dumps({"updates": updates})}, {"content": "$100"}, judge()])
    result = run_conversation(case, {"memory_policy": {"max_items": 1}}, transport, "q", "r")
    assert [item["accepted"] for item in result["memory_events"]] == [True, True, False, True, True]
    assert '"language": "English"' in transport.calls[1][1][0]["content"]


def test_fixture_scope_retained():
    case = scenario()
    case["fixture"]["scope"] = "household"
    transport = Transport([
        {"tool_calls": [{"id": "t", "function": {"name": "get_metrics", "arguments": "{}"}}]},
        {"content": "$100"}, judge()])
    result = run_conversation(case, {}, transport, "q", "r")
    assert result["turns"][0]["tool_trace"][0]["result"]["scope"] == "household"
