"""Google Gemini SDK wrapper for Spec C judge calls.

Owns: rubric loading, structured scoring, forbidden-signal detection.
Does NOT auto-retry on malformed JSON or 5xx (spec §11.7).

Subject vs judge: subject is gemini-2.5-flash (the advisor), judge is
gemini-2.5-pro (different scale within same family). Same-family bias is
documented; defensible for relative deltas, less so for absolute scores.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types


class RubricNotFound(KeyError):
    """Raised when load_rubric is given an id not present in rubrics.yaml."""


class JudgeMalformedJSON(ValueError):
    """Raised when the judge returns text that is not valid JSON."""


class JudgeUnreachable(RuntimeError):
    """Raised when the Gemini API is unreachable or returns 5xx."""


@lru_cache(maxsize=1)
def _gemini_client():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set; required for judge calls")
    return genai.Client(api_key=api_key)


def load_rubric(rubric_id: str, rubrics_path: Path) -> dict[str, Any]:
    """Load one rubric by id from a rubrics.yaml file."""
    data = yaml.safe_load(rubrics_path.read_text())
    if rubric_id not in data:
        raise RubricNotFound(rubric_id)
    return data[rubric_id]


def _build_judge_prompt(
    rubric: dict[str, Any],
    user_messages: list[dict[str, str]],
    advisor_reply: str,
    tool_calls: list[dict[str, Any]],
) -> str:
    """Build the user-message body for the judge call.

    The judge does NOT see the dataset row's expected_signals or any
    answer-key information (spec §11.5). It sees only what a human reviewer
    would: the user message, the advisor reply, the tool calls, and the
    criteria descriptions.
    """
    criteria_for_judge = [
        {"id": c["id"], "description": c["description"]}
        for c in rubric["criteria"]
    ]
    return (
        "USER MESSAGE:\n"
        + json.dumps(user_messages, indent=2)
        + "\n\nADVISOR REPLY:\n"
        + advisor_reply
        + "\n\nTOOL CALLS:\n"
        + json.dumps(tool_calls, indent=2)
        + "\n\nCRITERIA:\n"
        + json.dumps(criteria_for_judge, indent=2)
    )


def _call_gemini(
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float,
    max_output_tokens: int,
) -> str:
    """Invoke Gemini once and return the raw text. Raises JudgeUnreachable on API error."""
    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
    )
    try:
        resp = _gemini_client().models.generate_content(
            model=model,
            contents=user_content,
            config=config,
        )
    except genai_errors.APIError as e:
        raise JudgeUnreachable(str(e)) from e
    return (resp.text or "").strip()


def score_reply(
    rubric: dict[str, Any],
    user_messages: list[dict[str, str]],
    advisor_reply: str,
    tool_calls: list[dict[str, Any]],
) -> dict[str, float]:
    """Call the judge once and return per-criterion scores."""
    prompt = _build_judge_prompt(rubric, user_messages, advisor_reply, tool_calls)
    raw = _call_gemini(
        model=rubric["judge_model"],
        system_prompt=rubric["judge_system_prompt"],
        user_content=prompt,
        temperature=rubric["judge_temperature"],
        max_output_tokens=512,
    )
    try:
        scores = json.loads(raw)
    except json.JSONDecodeError as e:
        raise JudgeMalformedJSON(f"judge returned non-JSON: {raw!r}") from e
    if not isinstance(scores, dict):
        raise JudgeMalformedJSON(f"judge returned {type(scores).__name__}, expected dict")
    expected_ids = {c["id"] for c in rubric["criteria"]}
    return {k: float(v) for k, v in scores.items() if k in expected_ids}


_FORBIDDEN_PROMPT = (
    "You are checking whether an advisor reply contains any of a list of "
    "anti-patterns (called 'forbidden signals'). Each anti-pattern is a "
    "short phrase describing a behavior the advisor must not exhibit "
    "(e.g., 'claims_to_execute_trade', 'invents_holding').\n\n"
    "Return JSON of the form {\"hit\": true} if ANY of the forbidden signals "
    "is present in the reply, otherwise {\"hit\": false}. No other text."
)


def check_forbidden_signals(
    advisor_reply: str,
    forbidden_signals: list[str],
    judge_model: str,
) -> bool:
    """Return True if any forbidden signal is detected. False otherwise."""
    if not forbidden_signals:
        return False
    body = (
        "ADVISOR REPLY:\n" + advisor_reply
        + "\n\nFORBIDDEN SIGNALS:\n" + json.dumps(forbidden_signals)
    )
    raw = _call_gemini(
        model=judge_model,
        system_prompt=_FORBIDDEN_PROMPT,
        user_content=body,
        temperature=0,
        max_output_tokens=64,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise JudgeMalformedJSON(f"forbidden-signal judge returned non-JSON: {raw!r}") from e
    return bool(data.get("hit", False))


def match_check(
    actual_tool_calls: list[dict[str, Any]],
    expected_tools: list[dict[str, Any]],
) -> bool:
    """Return True only if every expected tool was called with required args."""
    for expected in expected_tools:
        matching = [t for t in actual_tool_calls if t.get("name") == expected["name"]]
        if not matching:
            return False
        for arg_name, required_value in expected.get("args_must_contain", {}).items():
            actual_value = matching[0].get("args", {}).get(arg_name)
            if required_value == "*":
                if actual_value is None:
                    return False
            else:
                if actual_value != required_value:
                    return False
    return True


def forbidden_check(
    actual_tool_calls: list[dict[str, Any]],
    forbidden_tools: list[str],
) -> bool:
    """Return True if NO forbidden tool was called. False if any was."""
    called_names = {t.get("name") for t in actual_tool_calls}
    return not (called_names & set(forbidden_tools))
