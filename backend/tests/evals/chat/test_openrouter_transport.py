"""Budgeted transport tests use httpx mock transports exclusively."""
import json

import httpx
import pytest

from tests.evals.chat.offline_control import Ledger, PendingCall, BudgetExceeded


@pytest.fixture
def ledger(tmp_path):
    with Ledger(tmp_path / "ledger.sqlite") as value:
        value.add_question("q", {})
        value.start_round("q")
        yield value


def make_transport(ledger, handler):
    from tests.evals.chat.openrouter_transport import OpenRouterTransport
    return OpenRouterTransport(ledger, "fake-secret", client=httpx.Client(
        transport=httpx.MockTransport(handler)))


def response(cost=0.0010001, model="deepseek/deepseek-v3.2"):
    return {"id": "gen-1", "model": model, "provider": "test-provider",
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
            "usage": {"cost": cost, "prompt_tokens": 10, "completion_tokens": 5}}


@pytest.mark.parametrize("role,model", [("advisor", "deepseek/deepseek-v3.2"),
    ("judge", "google/gemini-2.5-flash"), ("memory", "google/gemini-2.5-flash")])
def test_role_routing_reservation_and_usage(ledger, role, model):
    def handler(request):
        assert ledger.summary("q")["pending_call_ids"] == ["c"]
        body = json.loads(request.content)
        assert body["model"] == model
        assert body["provider"]["require_parameters"] is True
        assert body["provider"]["allow_fallbacks"] is False
        assert body["provider"]["max_price"] == {"prompt": 2, "completion": 8, "request": 0}
        assert body["max_tokens"] == 1024
        return httpx.Response(200, json=response(model=model))
    result = make_transport(ledger, handler).complete("q", "c", role,
        [{"role": "user", "content": "hi"}])
    assert result["_telemetry"]["cost_microusd"] == 1001
    assert result["_telemetry"]["provider"] == "test-provider"
    assert result["_telemetry"]["latency_seconds"] >= 0
    assert ledger.summary("q")["spent_microusd"] == 1001


def test_cache_is_request_and_question_bound(ledger):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response())
    transport = make_transport(ledger, handler)
    messages = [{"role": "user", "content": "hi"}]
    first = transport.complete("q", "c", "advisor", messages)
    assert transport.complete("q", "c", "advisor", messages) == first
    for question, role, msg in [("other", "advisor", messages), ("q", "judge", messages),
                               ("q", "advisor", [{"role": "user", "content": "changed"}])]:
        with pytest.raises(ValueError, match="request"):
            transport.complete(question, "c", role, msg)
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["timeout", "missing", "invalid", "http"])
def test_unknown_cost_blocks_retry(ledger, kind):
    calls = []
    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("timeout")
        if kind == "invalid":
            return httpx.Response(200, json=response(-1))
        return httpx.Response(503 if kind == "http" else 200, json={"error": "unknown"})
    transport = make_transport(ledger, handler)
    with pytest.raises(RuntimeError):
        transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])
    with pytest.raises(PendingCall):
        transport.complete("q", "c2", "advisor", [{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_known_error_cost_is_saved_and_replayed_without_http(ledger):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "unavailable"},
                                       "usage": {"cost": .002}})
    transport = make_transport(ledger, handler)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="503"):
            transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])
    assert ledger.summary("q")["spent_microusd"] == 2000
    assert ledger.summary("q")["pending_call_ids"] == []
    assert len(calls) == 1


def test_budget_denies_before_network_and_overrun_is_recorded(ledger):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response(1.01))
    transport = make_transport(ledger, handler)
    with pytest.raises(BudgetExceeded):
        transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])
    assert ledger.summary("q")["spent_microusd"] == 1010000
    with pytest.raises(BudgetExceeded):
        transport.complete("q", "c2", "advisor", [{"role": "user", "content": "hi"}])
    assert len(calls) == 1


@pytest.mark.parametrize("kwargs", [{"role": "unknown"}, {"max_tokens": 0},
    {"max_tokens": True}, {"max_tokens": 1000000}, {"reasoning_effort": "custom"},
    {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]},
    {"messages": [{"role": "user", "content": "x" * 100000}]},
    {"tools": [{"type": "web_search"}]}])
def test_unbounded_inputs_rejected_before_reservation(ledger, kwargs):
    transport = make_transport(ledger, lambda _: pytest.fail("Unexpected network"))
    args = dict(question_id="q", call_id="c", role="advisor",
                messages=[{"role": "user", "content": "hi"}])
    args.update(kwargs)
    with pytest.raises(ValueError):
        transport.complete(**args)
    assert ledger.summary("q")["call_count"] == 0


def test_tools_reasoning_format_and_utf8_are_in_bound(ledger):
    def handler(request):
        body = json.loads(request.content)
        assert body["reasoning"] == {"enabled": True}
        assert body["tools"][0]["function"]["name"] == "snapshot"
        assert body["response_format"] == {"type": "json_object"}
        assert ledger.summary("q")["reserved_microusd"] >= len(request.content) * 2 + 100 * 8
        return httpx.Response(200, json=response())
    make_transport(ledger, handler).complete("q", "c", "advisor",
        [{"role": "user", "content": "\u7b97\u76d8"}], max_tokens=100,
        tools=[{"type": "function", "function": {"name": "snapshot", "parameters": {}}}],
        reasoning_effort="low", response_format={"type": "json_object"})


def test_insufficient_shared_budget_never_dispatches(ledger):
    ledger.reserve("q", "prior", 990000)
    ledger.settle("prior", 990000, {})
    transport = make_transport(ledger, lambda _: pytest.fail("Unexpected network"))
    with pytest.raises(BudgetExceeded):
        transport.complete("q", "c", "memory", [{"role": "user", "content": "hi"}])
    assert ledger.summary("q")["call_count"] == 1


def test_policy_is_immutable_and_caller_cannot_override_price_or_model(ledger):
    from dataclasses import FrozenInstanceError
    from tests.evals.chat.openrouter_transport import PRICING, MODELS
    with pytest.raises(FrozenInstanceError):
        PRICING.prompt_usd_per_million = 0
    with pytest.raises(TypeError):
        MODELS["advisor"] = "free-model"
    transport = make_transport(ledger, lambda _: pytest.fail("Unexpected network"))
    for override in [{"model": "free-model"}, {"max_price": 0}, {"budget": 100}]:
        with pytest.raises(TypeError):
            transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}], **override)


@pytest.mark.parametrize("cost", [None, True, "NaN", "Infinity", "bad"])
def test_invalid_accounting_never_releases_reservation(ledger, cost):
    transport = make_transport(ledger, lambda _: httpx.Response(200, json=response(cost)))
    with pytest.raises(RuntimeError):
        transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])
    assert ledger.summary("q")["pending_call_ids"] == ["c"]


@pytest.mark.parametrize("field,value", [("model", "other-model"), ("model", None),
    ("provider", None), ("provider", ""), ("prompt_tokens", None),
    ("completion_tokens", True), ("completion_tokens", -1)])
def test_paid_invalid_telemetry_is_recorded_then_stops_question(ledger, field, value):
    payload = response()
    (payload["usage"] if field.endswith("tokens") else payload)[field] = value
    transport = make_transport(ledger, lambda _: httpx.Response(200, json=payload))
    with pytest.raises(RuntimeError, match="telemetry"):
        transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])
    assert ledger.summary("q")["spent_microusd"] == 1001
    assert ledger.summary("q")["pending_call_ids"] == []
    assert ledger.summary("q")["stop_reason"] == "invalid_provider_telemetry"


@pytest.mark.parametrize("role,effort,expected", [("advisor", None, {"enabled": False}),
    ("advisor", "none", {"enabled": False}), ("advisor", "low", {"enabled": True}),
    ("judge", "low", {"effort": "low"})])
def test_reasoning_controls_match_model_contract(ledger, role, effort, expected):
    from tests.evals.chat.openrouter_transport import MODELS
    def handler(request):
        assert json.loads(request.content)["reasoning"] == expected
        return httpx.Response(200, json=response(model=MODELS[role]))
    make_transport(ledger, handler).complete("q", "c", role,
        [{"role": "user", "content": "hi"}], reasoning_effort=effort)


def test_reasoning_details_round_trip_as_bounded_text_metadata(ledger):
    details = [{"type": "reasoning.text", "text": "Need snapshot", "index": 0}]
    messages = [{"role": "assistant", "content": None, "reasoning": "Need snapshot",
                 "reasoning_details": details, "tool_calls": [{"id": "t", "type": "function",
                    "function": {"name": "snapshot", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "t", "content": "{}"}]
    def handler(request):
        assert json.loads(request.content)["messages"] == messages
        return httpx.Response(200, json=response())
    make_transport(ledger, handler).complete("q", "c", "advisor", messages)


def pending_transport(ledger, payload=None):
    def handler(_):
        if payload is not None:
            return httpx.Response(200, json=payload)
        raise httpx.ReadTimeout("unknown")
    transport = make_transport(ledger, handler)
    with pytest.raises(RuntimeError):
        transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])
    return transport


def test_verified_receipt_settles_pending_and_reuses_original_cache(ledger):
    transport = pending_transport(ledger)
    row = ledger.db.execute("SELECT * FROM transport_requests WHERE call_id='c'").fetchone()
    assert row["question"] == "q"
    assert row["requested_model"] == "deepseek/deepseek-v3.2"
    assert "fake-secret" not in str(dict(row))
    result = transport.reconcile("c", response(), latency_seconds=2.5)
    assert result["_telemetry"]["latency_seconds"] == 2.5
    assert ledger.summary("q")["spent_microusd"] == 1001
    assert ledger.summary("q")["pending_call_ids"] == []
    assert transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}]) == result
    with pytest.raises(ValueError):
        transport.reconcile("c", response(), latency_seconds=2.5)


def test_pending_request_cannot_change_identity(ledger):
    transport = pending_transport(ledger)
    before = dict(ledger.db.execute("SELECT * FROM transport_requests WHERE call_id='c'").fetchone())
    with pytest.raises(ValueError, match="request"):
        transport.complete("q", "c", "judge", [{"role": "user", "content": "changed"}])
    assert dict(ledger.db.execute("SELECT * FROM transport_requests WHERE call_id='c'").fetchone()) == before


@pytest.mark.parametrize("change", [{"model": "wrong"}, {"provider": None}, {"id": None},
    {"usage": {"prompt_tokens": 1, "completion_tokens": 1}},
    {"usage": {"cost": None, "prompt_tokens": 1, "completion_tokens": 1}}])
def test_unverified_receipt_cannot_clear_pending(ledger, change):
    transport = pending_transport(ledger)
    with pytest.raises((ValueError, RuntimeError)):
        transport.reconcile("c", response() | change, latency_seconds=1)
    assert ledger.summary("q")["pending_call_ids"] == ["c"]
    with pytest.raises(ValueError):
        transport.reconcile("unknown-call", response(), latency_seconds=1)


def test_reconciliation_checks_observed_provider_response_id(ledger):
    incomplete = response()
    incomplete.pop("usage")
    transport = pending_transport(ledger, incomplete)
    with pytest.raises(ValueError, match="identity"):
        transport.reconcile("c", response() | {"id": "different-generation"}, latency_seconds=1)
    assert ledger.summary("q")["pending_call_ids"] == ["c"]


def test_unknown_reconciled_latency_stops_quality_scoring_but_records_cost(ledger):
    transport = pending_transport(ledger)
    with pytest.raises(RuntimeError, match="latency"):
        transport.reconcile("c", response())
    assert ledger.summary("q")["spent_microusd"] == 1001
    assert ledger.summary("q")["stop_reason"] == "unknown_reconciled_latency"
    with pytest.raises(RuntimeError, match="telemetry"):
        transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])


def test_reconciliation_retains_budget_overrun_and_stop(ledger):
    transport = pending_transport(ledger)
    with pytest.raises(BudgetExceeded):
        transport.reconcile("c", response(1.01), latency_seconds=1)
    assert ledger.summary("q")["spent_microusd"] == 1010000
    assert ledger.summary("q")["budget_breach"] is True


def test_reconciliation_survives_connection_restart(tmp_path):
    path = tmp_path / "durable.sqlite"
    with Ledger(path) as first:
        first.add_question("q", {})
        first.start_round("q")
        pending_transport(first)
    with Ledger(path) as second:
        transport = make_transport(second, lambda _: pytest.fail("Unexpected network"))
        transport.reconcile("c", response(), latency_seconds=3)
        assert transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])["id"] == "gen-1"


def test_receipt_cannot_be_reused_to_clear_another_pending_call(ledger):
    transport = pending_transport(ledger)
    transport.reconcile("c", response(), latency_seconds=1)
    with pytest.raises(RuntimeError):
        transport.complete("q", "second", "advisor", [{"role": "user", "content": "next"}])
    with pytest.raises(ValueError, match="identity"):
        transport.reconcile("second", response(), latency_seconds=1)
    assert ledger.summary("q")["pending_call_ids"] == ["second"]


def test_verified_error_receipt_records_charge_without_retry(ledger):
    transport = pending_transport(ledger)
    payload = response() | {"error": {"message": "failed"}}
    with pytest.raises(RuntimeError, match="503"):
        transport.reconcile("c", payload, status_code=503, latency_seconds=1)
    with pytest.raises(RuntimeError, match="503"):
        transport.complete("q", "c", "advisor", [{"role": "user", "content": "hi"}])
    assert ledger.summary("q")["spent_microusd"] == 1001
    assert ledger.summary("q")["call_count"] == 1
