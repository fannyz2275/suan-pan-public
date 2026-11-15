"""Spec C runner — drives /advisor/chat against scored rubrics."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Load backend/.env so ANTHROPIC_API_KEY (and others) reach os.environ.
# Locating .env relative to this file makes the runner work regardless of cwd.
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[3] / "backend" / ".env")

from tests.evals.chat import EVAL_USER_ID
from tests.evals.chat.chat_session import ChatSession
from tests.evals.chat.judge import (
    JudgeMalformedJSON,
    JudgeUnreachable,
    forbidden_check,
    load_rubric,
    match_check,
    score_reply,
    check_forbidden_signals,
)
from tests.evals.chat.report import now_utc_iso, write_json, write_markdown_summary
from tests.evals.chat.seeds import get_seed

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"
RUBRICS_PATH = Path(__file__).parent / "rubrics.yaml"


# Indirection points that tests patch
def _make_chat_session() -> ChatSession:
    base_url = os.getenv("EVAL_BASE_URL", "http://localhost:8000")
    return ChatSession(base_url=base_url, user_id=EVAL_USER_ID)


def _apply_seed(seed_id: str) -> None:
    """Apply the named seed to the configured Supabase test DB."""
    from app.config import settings
    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_service_key)
    seed = get_seed(seed_id)
    seed.apply(client)


def run_one_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    rubric = load_rubric(scenario["judge_prompt_id"], RUBRICS_PATH)

    _apply_seed(scenario["setup"]["seed_id"])

    runs: list[dict[str, Any]] = []
    for run_idx in range(scenario["n_runs"]):
        criterion_scores: dict[str, float] = {}
        run_score: float = 0.0
        tags: list[str] = []
        tools_expected_ok = False
        tools_forbidden_ok = False
        forbidden_signal_hit = False

        try:
            session = _make_chat_session()
            for msg in scenario["messages"]:
                reply, tool_calls = session.send(msg)
        except Exception as exc:  # noqa: BLE001
            runs.append({
                "run_idx": run_idx, "score": 0.0,
                "tools_expected_ok": False, "tools_forbidden_ok": False,
                "criterion_scores": {}, "tags": ["[ADVISOR-ERROR]"],
                "error": str(exc),
            })
            continue

        if not reply or not reply.strip():
            runs.append({
                "run_idx": run_idx, "score": 0.0,
                "tools_expected_ok": False, "tools_forbidden_ok": False,
                "criterion_scores": {}, "tags": ["[ADVISOR-ERROR]"],
            })
            continue

        tools_expected_ok = match_check(tool_calls, scenario["expected_tools"])
        tools_forbidden_ok = forbidden_check(tool_calls, scenario.get("forbidden_tools", []))

        try:
            forbidden_signal_hit = check_forbidden_signals(
                advisor_reply=reply,
                forbidden_signals=scenario.get("forbidden_signals", []),
                judge_model=rubric["judge_model"],
            )
        except JudgeUnreachable:
            runs.append({
                "run_idx": run_idx, "score": 0.0,
                "tools_expected_ok": tools_expected_ok,
                "tools_forbidden_ok": tools_forbidden_ok,
                "criterion_scores": {}, "tags": ["[JUDGE-UNREACHABLE]"],
            })
            continue
        except JudgeMalformedJSON:
            runs.append({
                "run_idx": run_idx, "score": 0.0,
                "tools_expected_ok": tools_expected_ok,
                "tools_forbidden_ok": tools_forbidden_ok,
                "criterion_scores": {}, "tags": ["[JUDGE-LOW-CONFIDENCE]"],
            })
            continue

        if not tools_expected_ok:
            tags.append("[TOOL-MISS]")
        if not tools_forbidden_ok:
            tags.append("[TOOL-EXTRA]")
        if forbidden_signal_hit:
            tags.append("[FAKE-ACTION]")

        if tags:
            runs.append({
                "run_idx": run_idx, "score": 0.0,
                "tools_expected_ok": tools_expected_ok,
                "tools_forbidden_ok": tools_forbidden_ok,
                "criterion_scores": {}, "tags": tags,
            })
            continue

        try:
            criterion_scores = score_reply(
                rubric=rubric,
                user_messages=scenario["messages"],
                advisor_reply=reply,
                tool_calls=tool_calls,
            )
        except JudgeUnreachable:
            runs.append({
                "run_idx": run_idx, "score": 0.0,
                "tools_expected_ok": tools_expected_ok,
                "tools_forbidden_ok": tools_forbidden_ok,
                "criterion_scores": {}, "tags": ["[JUDGE-UNREACHABLE]"],
            })
            continue
        except JudgeMalformedJSON:
            runs.append({
                "run_idx": run_idx, "score": 0.0,
                "tools_expected_ok": tools_expected_ok,
                "tools_forbidden_ok": tools_forbidden_ok,
                "criterion_scores": {}, "tags": ["[JUDGE-LOW-CONFIDENCE]"],
            })
            continue

        run_score = sum(
            s["weight"] * criterion_scores.get(s["id"], 0.0)
            for s in scenario["expected_signals"]
        )
        for signal in scenario["expected_signals"]:
            if signal.get("required") and criterion_scores.get(signal["id"], 0.0) == 0.0:
                run_score = 0.0
                break

        runs.append({
            "run_idx": run_idx, "score": run_score,
            "tools_expected_ok": tools_expected_ok,
            "tools_forbidden_ok": tools_forbidden_ok,
            "criterion_scores": criterion_scores, "tags": tags,
        })

    scored = [r for r in runs
              if "[ADVISOR-ERROR]" not in r["tags"]
              and "[JUDGE-UNREACHABLE]" not in r["tags"]
              and "[JUDGE-LOW-CONFIDENCE]" not in r["tags"]]
    pass_count = sum(r["score"] >= scenario["pass_threshold"] for r in scored)
    scenario_pass = pass_count >= 2 and len(scored) >= 2

    if pass_count in (1, 2) and not scenario_pass:
        for r in runs:
            r["tags"].append("[FLAKY]")

    return {
        "id": scenario["id"],
        "tags": scenario["tags"],
        "judge_prompt_id": scenario["judge_prompt_id"],
        "runs": runs,
        "pass_count": pass_count,
        "scenario_pass": scenario_pass,
    }


def load_dataset(path: Path = DATASET_PATH) -> tuple[dict, list[dict]]:
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    parsed = [json.loads(l) for l in lines]
    return parsed[0], parsed[1:]


def _system_prompt_hash() -> str:
    try:
        from app.advisor.context import SYSTEM_PROMPT  # type: ignore
        return hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]
    except Exception:
        return "unknown"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
        ).decode().strip()[:12]
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spec C chat-advisor quality eval")
    parser.add_argument("--tags", default=None, help="comma-separated tag filter")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-cost-cents", type=int, default=100,
                        help="Legacy flag; live runs disabled until budgeted transport is wired.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate dataset only; no API calls.")
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args(argv)

    if not args.dry_run:
        print("Live evaluations disabled: this legacy runner does not enforce the "
              "USD 1.00 conversation cap. Use dry-run until budgeted transport is wired.",
              file=sys.stderr)
        return 2

    header, rows = load_dataset()
    if args.tags:
        wanted = set(args.tags.split(","))
        rows = [r for r in rows if wanted & set(r.get("tags", []))]
    if args.limit:
        rows = rows[: args.limit]

    if args.dry_run:
        print(f"Dataset valid: {len(rows)} scenarios after filters.")
        return 0

    scenarios_out: list[dict] = []
    for row in rows:
        scenarios_out.append(run_one_scenario(row))

    counter: Counter[str] = Counter()
    for s in scenarios_out:
        n = len(s["runs"])
        counter[f"{s['pass_count']}/{n}"] += 1

    report = {
        "header": {
            "run_date": now_utc_iso(),
            "dataset_version": header["dataset_version"],
            "system_prompt_version": _system_prompt_hash(),
            "subject_model": "gemini-2.5-flash",
            "judge_model": "gemini-2.5-pro",
            "suan_pan_sha": _git_sha(),
        },
        "distribution": dict(counter),
        "scenarios": scenarios_out,
    }

    ts = now_utc_iso()
    sha = report["header"]["suan_pan_sha"]
    json_path = (
        Path(args.report_out)
        if args.report_out
        else Path(__file__).parent / "reports" / f"report-{ts}-{sha}.json"
    )
    md_path = Path(__file__).resolve().parents[3] / "docs" / "test-reports" / f"eval-c-{ts}-{sha}.md"
    write_json(report, json_path)
    write_markdown_summary(report, md_path)
    print(f"Wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
