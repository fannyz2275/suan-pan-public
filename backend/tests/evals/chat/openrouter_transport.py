"""Single-request OpenRouter transport with durable, conservative reservations.

Pricing policy v1 accepts text and client-side function tools only. One serialized
UTF-8 byte is budgeted as one input token, plus 8192 framing tokens, 256 per
message, and 1024 per tool. Inputs above 100,000 bounded tokens are rejected.
This assumes byte-based tokenization and framing within that allowance; it is
not a provider billing guarantee. max_tokens budgets reasoning and visible output
together under OpenRouter's documented convention. A provider violating that
convention can overrun: the ledger records the charge and hard-stops the question.

Rates are acceptance ceilings, not advertised model prices. No paid server tools,
multimodal payloads, cache-control directives, or request surcharges are allowed.
An injected client must be a retry-free httpx client (normally MockTransport).

References:
https://openrouter.ai/docs/guides/routing/provider-selection
https://openrouter.ai/docs/cookbook/administration/usage-accounting
https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
https://openrouter.ai/deepseek/deepseek-v3.2
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import math
import time
from types import MappingProxyType

import httpx

from .offline_control import Ledger


@dataclass(frozen=True)
class PricingPolicy:
    version: str = "openrouter-text-v1-2026-10-11"
    prompt_usd_per_million: int = 2
    completion_usd_per_million: int = 8
    input_token_cap: int = 100_000
    output_token_cap: int = 16_384


PRICING = PricingPolicy()
MODELS = MappingProxyType({"advisor": "deepseek/deepseek-v3.2",
                          "judge": "google/gemini-2.5-flash",
                          "memory": "google/gemini-2.5-flash"})
URL = "https://openrouter.ai/api/v1/chat/completions"


class TransportError(RuntimeError):
    """A failed request; consult the ledger before any further action."""


def _serialize(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _cost(payload: dict) -> int:
    usage = payload.get("usage")
    cost = usage.get("cost") if isinstance(usage, dict) else None
    if isinstance(cost, bool) or not isinstance(cost, (int, float, str)):
        raise TransportError("Missing confirmed usage cost; reservation remains pending")
    try:
        value = Decimal(str(cost))
        if not value.is_finite() or value < 0:
            raise InvalidOperation
        return int((value * 1_000_000).to_integral_value(rounding=ROUND_CEILING))
    except (InvalidOperation, ValueError, OverflowError):
        raise TransportError("Invalid usage cost; reservation remains pending") from None


def _valid_identity(payload: dict, model: str) -> bool:
    usage = payload.get("usage")
    return (payload.get("model") == model
            and isinstance(payload.get("provider"), str) and bool(payload["provider"].strip())
            and isinstance(usage, dict)
            and all(type(usage.get(key)) is int and usage[key] >= 0
                    for key in ("prompt_tokens", "completion_tokens")))


def _valid_latency(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class OpenRouterTransport:
    supports_reasoning_details = True

    def __init__(self, ledger: Ledger, api_key: str, *, client=None):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("An explicit API key is required")
        self.ledger = ledger
        self._api_key = api_key
        self._client = client
        self.ledger.db.execute("""CREATE TABLE IF NOT EXISTS transport_requests (
            call_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
            question TEXT NOT NULL, requested_model TEXT NOT NULL,
            pricing_version TEXT NOT NULL, provider_response_id TEXT UNIQUE
        )""")

    def reconcile(self, call_id: str, provider_response: dict, status_code: int = 200,
                  latency_seconds: float | None = None) -> dict:
        """Settle an operator-verified receipt; never issue a provider request.

        The trusted local operator must verify that the receipt belongs to this
        call. If a timeout hid the generation ID entirely, model/provider checks
        cannot independently prove that association. Receipts are never accepted
        from model output or used to create calls, raise budgets, or clear stops.
        """
        request = self.ledger.db.execute(
            "SELECT * FROM transport_requests WHERE call_id=?", (call_id,)).fetchone()
        call = self.ledger.db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if request is None or call is None or call["actual"] is not None:
            raise ValueError("Only a known pending transport call can be reconciled")
        if (call["question"] != request["question"] or not isinstance(provider_response, dict)
                or not _valid_identity(provider_response, request["requested_model"])
                or not isinstance(provider_response.get("id"), str) or not provider_response["id"]):
            raise ValueError("Provider receipt identity or usage is invalid")
        receipt_id = provider_response["id"]
        observed = request["provider_response_id"]
        reused = self.ledger.db.execute(
            "SELECT call_id FROM transport_requests WHERE provider_response_id=? AND call_id<>?",
            (receipt_id, call_id)).fetchone()
        if (observed is not None and observed != receipt_id) or reused:
            raise ValueError("Provider receipt identity does not match the original call")
        if type(status_code) is not int or not 100 <= status_code <= 599:
            raise ValueError("Invalid receipt status")
        if latency_seconds is not None and not _valid_latency(latency_seconds):
            raise ValueError("Invalid receipt latency")
        actual = _cost(provider_response)
        payload = json.loads(_serialize(provider_response))
        payload["_telemetry"] = dict(cost_microusd=actual, latency_seconds=latency_seconds,
            model=payload["model"], provider=payload["provider"], usage=payload["usage"],
            pricing_version=request["pricing_version"], reconciled=True)
        self.ledger.db.execute("UPDATE transport_requests SET provider_response_id=? WHERE call_id=?",
                               (receipt_id, call_id))
        self.ledger.settle(call_id, actual, dict(request_hash=request["request_hash"],
                                               response=payload, status_code=status_code))
        if latency_seconds is None:
            self.ledger.stop(request["question"], "unknown_reconciled_latency")
            raise TransportError("Cost reconciled but unknown latency prevents quality scoring")
        if not 200 <= status_code < 300 or payload.get("error"):
            raise TransportError(f"Provider returned error HTTP {status_code}; cost recorded")
        return payload

    def complete(self, question_id: str, call_id: str, role: str,
                 messages: list[dict], *, tools: list | None = None,
                 max_tokens: int = 1024, reasoning_effort: str | None = None,
                 response_format: dict | None = None) -> dict:
        if role not in MODELS:
            raise ValueError("Unsupported transport role")
        if type(max_tokens) is not int or not 1 <= max_tokens <= PRICING.output_token_cap:
            raise ValueError("Output token limit is outside the pricing policy")
        if reasoning_effort not in (None, "none", "minimal", "low", "medium", "high"):
            raise ValueError("Unsupported reasoning effort")
        if not isinstance(messages, list) or not messages:
            raise ValueError("Nonempty text messages required")
        for message in messages:
            if (not isinstance(message, dict)
                    or set(message) - {"role", "content", "name", "tool_calls", "tool_call_id",
                                       "reasoning", "reasoning_details"}
                    or message.get("role") not in {"system", "user", "assistant", "tool"}
                    or (message.get("content") is not None and not isinstance(message["content"], str))):
                raise ValueError("Only plain text messages and function tool calls are bounded")
            if "reasoning" in message and not isinstance(message["reasoning"], str):
                raise ValueError("Reasoning metadata must be text")
            if "reasoning_details" in message and (not isinstance(message["reasoning_details"], list)
                    or any(not isinstance(detail, dict) or detail.get("type") not in {
                        "reasoning.text", "reasoning.summary", "reasoning.encrypted"}
                        for detail in message["reasoning_details"])):
                raise ValueError("Unsupported reasoning metadata")
            for call in message.get("tool_calls", []):
                if not isinstance(call, dict) or call.get("type") != "function":
                    raise ValueError("Only client-side function calls are supported")
        if tools is not None and (not isinstance(tools, list) or any(
                not isinstance(tool, dict) or tool.get("type") != "function"
                or set(tool) - {"type", "function"} or not isinstance(tool.get("function"), dict)
                for tool in tools)):
            raise ValueError("Only client-side function tools are supported")
        if response_format is not None and (not isinstance(response_format, dict)
                or response_format.get("type") not in {"json_object", "json_schema", "text"}):
            raise ValueError("Unsupported response format")
        body = dict(model=MODELS[role], messages=messages, max_tokens=max_tokens,
                    stream=False, provider=dict(require_parameters=True, allow_fallbacks=False,
                        max_price=dict(prompt=PRICING.prompt_usd_per_million,
                                       completion=PRICING.completion_usd_per_million, request=0)))
        if tools is not None:
            body["tools"] = tools
        if role == "advisor":
            # V3.2 documents only an enabled switch; effort levels do not select strength.
            body["reasoning"] = {"enabled": reasoning_effort not in (None, "none")}
        elif reasoning_effort is not None:
            body["reasoning"] = {"effort": reasoning_effort}
        if response_format is not None:
            body["response_format"] = response_format
        serialized = _serialize(body)
        input_bound = len(serialized) + 8192 + 256 * len(messages) + 1024 * len(tools or [])
        if input_bound > PRICING.input_token_cap:
            raise ValueError("Serialized input exceeds the conservative input token cap")
        reservation = (input_bound * PRICING.prompt_usd_per_million
                       + max_tokens * PRICING.completion_usd_per_million)
        request_hash = hashlib.sha256(_serialize(dict(question=question_id, role=role,
            pricing=PRICING.version, body=body))).hexdigest()
        saved = self.ledger.cached(call_id)
        if saved is None:
            self.ledger.db.execute("""INSERT OR IGNORE INTO transport_requests
                (call_id, request_hash, question, requested_model, pricing_version)
                VALUES (?,?,?,?,?)""", (call_id, request_hash, question_id, MODELS[role], PRICING.version))
            original = self.ledger.db.execute(
                "SELECT request_hash FROM transport_requests WHERE call_id=?", (call_id,)).fetchone()
            if original["request_hash"] != request_hash:
                raise ValueError("Call ID belongs to a different request")
            def dispatch():
                started = time.monotonic()
                headers = {"Authorization": f"Bearer {self._api_key}",
                           "Content-Type": "application/json"}
                try:
                    if self._client is None:
                        with httpx.Client(transport=httpx.HTTPTransport(retries=0),
                                          trust_env=False, follow_redirects=False) as client:
                            response = client.post(URL, content=serialized, headers=headers,
                                                   timeout=120, follow_redirects=False)
                    else:
                        response = self._client.post(URL, content=serialized, headers=headers,
                                                     timeout=120, follow_redirects=False)
                    payload = response.json()
                except (httpx.HTTPError, ValueError):
                    raise TransportError("Unknown provider outcome; reservation remains pending") from None
                if not isinstance(payload, dict):
                    raise TransportError("Invalid provider response; reservation remains pending")
                if isinstance(payload.get("id"), str) and payload["id"]:
                    self.ledger.db.execute("""UPDATE transport_requests SET provider_response_id=?
                        WHERE call_id=? AND provider_response_id IS NULL""", (payload["id"], call_id))
                actual = _cost(payload)
                payload["_telemetry"] = dict(cost_microusd=actual,
                    latency_seconds=time.monotonic() - started,
                    model=payload.get("model"), provider=payload.get("provider"),
                    usage=payload["usage"], pricing_version=PRICING.version)
                return actual, dict(request_hash=request_hash, response=payload,
                                    status_code=response.status_code)
            saved = self.ledger.dispatch(question_id, call_id, reservation, dispatch)
        if saved.get("request_hash") != request_hash:
            raise ValueError("Cached call ID belongs to a different request")
        payload = saved["response"]
        if not 200 <= saved["status_code"] < 300 or payload.get("error"):
            raise TransportError(f"Provider returned error HTTP {saved['status_code']}; cost recorded")
        if (not _valid_identity(payload, MODELS[role])
                or not _valid_latency(payload["_telemetry"].get("latency_seconds"))):
            self.ledger.stop(question_id, "invalid_provider_telemetry")
            raise TransportError("Invalid provider telemetry; cost recorded and question stopped")
        return payload
