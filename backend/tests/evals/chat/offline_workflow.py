"""CLI for Codex-operated, isolated advisor experiments. No production DB access."""
from __future__ import annotations

import argparse
import difflib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys

from tests.evals.chat.offline_control import (
    Ledger, BudgetExceeded, PendingCall, InvalidTransition, aggregate, passes,
)


def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def runtime_hash():
    root = Path(__file__).parent
    return digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in
                   ("offline_workflow.py", "offline_control.py", "offline_conversation.py", "openrouter_transport.py")})


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded(value) + "\n")
    temporary.replace(path)


def code_version():
    def git(*args):
        result = subprocess.run(["git", *args], capture_output=True, check=True)
        return result.stdout
    try:
        # Include untracked workflow sources, not environment files or financial data.
        sources = b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py")))
        return {"sha": git("rev-parse", "HEAD").decode().strip(),
                "dirty_diff_hash": hashlib.sha256(git("diff", "HEAD") + sources).hexdigest()}
    except (OSError, subprocess.CalledProcessError):
        return {"sha": "unavailable", "dirty_diff_hash": "unavailable"}


class Workflow:
    @staticmethod
    def create(path: Path, dataset: dict, setup: dict, *, candidate: dict | None = None):
        from tests.evals.chat.offline_conversation import validate_setup, validate_scenario
        if dataset.get("split") not in {"development", "holdout"}:
            raise ValueError("Dataset must declare development or holdout split")
        scenarios = [validate_scenario(s) for s in dataset.get("scenarios", [])]
        if not scenarios or len({s["id"] for s in scenarios}) != len(scenarios):
            raise ValueError("Require nonempty scenarios with unique IDs")
        if any(not 3 <= len(s["turns"]) <= 5 for s in scenarios):
            raise ValueError("Each workflow scenario requires 3-5 scripted turns")
        setup = validate_setup(setup)
        if dataset["split"] == "holdout" and candidate is None:
            raise ValueError("Holdout requires an already frozen candidate")
        candidate = validate_setup(candidate) if candidate is not None else None
        path.mkdir(parents=True, exist_ok=False)
        manifest = {"version": 1, "split": dataset["split"], "scenarios": scenarios,
                    "baseline": setup, "candidate": candidate, "code": code_version(),
                    "weights": [10, 8, 2, 2, 2, 2], "cap_microusd": 1_000_000,
                    "normalization": "unit-interval-v1", "rubric_version": "offline-v1",
                    "runtime_hash": runtime_hash()}
        with Ledger(path / "ledger.sqlite") as ledger:
            ledger.db.execute("CREATE TABLE artifacts (name TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            ledger.db.execute("INSERT INTO artifacts VALUES ('manifest',?)", (encoded(manifest),))
            ledger.db.execute("INSERT INTO artifacts VALUES ('tool_oracles',?)", (encoded(
                {tool["name"]: tool["tests"] for tool in setup.get("tools", [])}),))
        save(path / "manifest.json", manifest)

    def __init__(self, path: Path, *, executor=None):
        self.path = path
        self.lock = (path / "workflow.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise InvalidTransition("Another workflow command is active") from None
        self.ledger = Ledger(path / "ledger.sqlite")
        row = self.ledger.db.execute("SELECT payload FROM artifacts WHERE name='manifest'").fetchone()
        self.manifest = json.loads(row[0])
        if self.manifest["runtime_hash"] != runtime_hash():
            self.ledger.__exit__(None, None, None)
            self.lock.close()
            raise ValueError("Harness implementation changed; mixed-version runs are refused")
        if executor is None:
            from tests.evals.chat.offline_conversation import run_conversation
            executor = run_conversation
        self.executor = executor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.ledger.__exit__(*args)
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def _current(self):
        setup = self.manifest["baseline"]
        for scenario in self.manifest["scenarios"]:
            try:
                state = self.ledger.summary(scenario["id"])
            except InvalidTransition:
                self.ledger.add_question(scenario["id"], setup)
                state = self.ledger.summary(scenario["id"])
            if len(state["rounds"]) < 3 and not state.get("stop_reason"):
                return scenario, state
            setup = state["setup"]
        return None, None

    def step(self, transport):
        if self.manifest["split"] != "development":
            raise ValueError("holdout cannot be optimized; use replay")
        if self.ledger.db.execute("SELECT 1 FROM artifacts WHERE name='frozen'").fetchone():
            raise InvalidTransition("Setup frozen for replay; no more tuning")
        scenario, state = self._current()
        if scenario is None:
            self.report()
            return {"status": "development_complete"}
        question = scenario["id"]
        if state["active_round"] is None:
            if len(state["updates"]) < len(state["rounds"]):
                return {"status": "awaiting_update", "question": question}
            number = self.ledger.start_round(question)
        else:
            if state["pending_call_ids"]:
                raise PendingCall("Unknown previous provider outcome; reconcile before resuming")
            number = state["active_round"]
        try:
            result = self.executor(scenario, state["setup"], transport, question,
                                   f"{question}/round-{number}")
            self.ledger.finish_round(question, result["scores"], result["hard_failures"],
                                     result["turns"], result)
        except (BudgetExceeded, PendingCall):
            self.report()
            raise
        except Exception:
            # Preserve pending requests; do not manufacture a free retry on unknown outcomes.
            self.report()
            raise
        self.report()
        return {"status": "conversation_complete" if number == 3 else "awaiting_update",
                "question": question, "round": number}

    def update(self, candidate: dict, reason: str, cases: list[str]):
        from tests.evals.chat.offline_conversation import validate_setup
        if self.manifest["split"] == "holdout":
            raise ValueError("No updates from holdout results")
        if self.ledger.db.execute("SELECT 1 FROM artifacts WHERE name='frozen'").fetchone():
            raise InvalidTransition("Setup frozen for replay")
        scenario, state = self._current()
        if scenario is None:
            raise InvalidTransition("All conversations completed")
        allowed = {f"{scenario['id']}/{i}" for i in range(1, len(scenario["turns"]) + 1)}
        if not cases or not set(cases) <= allowed:
            raise ValueError("Trigger cases must identify turns in the current conversation")
        error = None
        try:
            candidate = validate_setup(candidate)
            # Frozen tests from previously accepted tools cannot be replaced by the optimizer.
            registry = json.loads(self.ledger.db.execute(
                "SELECT payload FROM artifacts WHERE name='tool_oracles'").fetchone()[0])
            for tool in candidate.get("tools", []):
                tests = {encoded(t): t for t in registry.get(tool["name"], []) + tool["tests"]}
                tool["tests"] = list(tests.values())
            validate_setup(candidate)
        except (ValueError, TypeError, KeyError) as exc:
            error = str(exc)
        diff = "\n".join(difflib.unified_diff(encoded(state["setup"]).splitlines(),
                        encoded(candidate).splitlines(), fromfile="before", tofile="candidate")) or "No-op"
        if error is None:
            for tool in candidate.get("tools", []):
                registry[tool["name"]] = tool["tests"]
        self.ledger.apply_update(scenario["id"], candidate, reason + (f" [rejected: {error}]" if error else ""),
                                 cases, diff, error is None, tool_oracles=registry if error is None else None)
        self.report()
        return {"retained": error is None, "validation_error": error}

    def _final_setup(self):
        setup = self.manifest["candidate"] or self.manifest["baseline"]
        for scenario in self.manifest["scenarios"]:
            try:
                setup = self.ledger.summary(scenario["id"])["setup"]
            except InvalidTransition:
                break
        return self.manifest["candidate"] or setup

    def replay(self, transport):
        if self.manifest["split"] == "development" and self._current()[0] is not None:
            raise InvalidTransition("Complete development conversations before frozen replay")
        final = self._final_setup()
        self.ledger.db.execute("INSERT OR IGNORE INTO artifacts VALUES ('frozen',?)", (encoded(final),))
        final = json.loads(self.ledger.db.execute("SELECT payload FROM artifacts WHERE name='frozen'").fetchone()[0])
        for index, scenario in enumerate(self.manifest["scenarios"]):
            question = scenario["id"]
            try:
                state = self.ledger.summary(question)
            except InvalidTransition:
                self.ledger.add_question(question, self.manifest["baseline"])
                state = self.ledger.summary(question)
            if state.get("stop_reason"):
                continue
            # Counterbalance fixed arm order without changing questions or fixtures.
            arms = ("baseline", "final") if index % 2 == 0 else ("final", "baseline")
            for arm in arms:
                if arm in state.get("replays", {}):
                    continue
                if state.get("active_replay") != arm:
                    self.ledger.start_replay(question, arm)
                setup = self.manifest["baseline"] if arm == "baseline" else final
                try:
                    result = self.executor(scenario, setup, transport, question, f"{question}/replay-{arm}")
                    self.ledger.finish_replay(question, result)
                finally:
                    self.report()
                return {"status": "replay_recorded", "question": question, "arm": arm}
        report = self.report()
        return {"status": "replay_complete", "gate": report["gate"]}

    def report(self):
        questions = []
        for scenario in self.manifest["scenarios"]:
            try:
                questions.append(self.ledger.summary(scenario["id"]))
            except InvalidTransition:
                break
        paired = []
        for question in questions:
            arms = question.get("replays", {})
            if "baseline" in arms and "final" in arms:
                paired.append(aggregate(arms["final"]["scores"]) - aggregate(arms["baseline"]["scores"]))
        interval = None
        if len(paired) >= 2:
            rng = random.Random(129)
            means = sorted(statistics.mean(rng.choices(paired, k=len(paired))) for _ in range(2000))
            interval = [means[49], means[1949]]
        final = self._final_setup()
        latency_samples = {phase: {role: [] for role in ("advisor", "memory", "judge")}
                           for phase in ("development", "baseline", "final")}
        for question in questions:
            batches = [("development", r.get("details", {})) for r in question["rounds"]]
            batches += list(question.get("replays", {}).items())
            for phase, batch in batches:
                for call in batch.get("call_records", []):
                    latency_samples[phase][call["role"]].append(call["latency_seconds"])
        # Nearest-rank percentiles keep small pilot samples interpretable.
        latencies = {}
        for phase, roles in latency_samples.items():
            latencies[phase] = {}
            for role, values in roles.items():
                ordered = sorted(values)
                latencies[phase][role] = {"count": len(ordered), **{
                    name: ordered[math.ceil(p * len(ordered)) - 1] if ordered else None
                    for name, p in (("p50", .5), ("p95", .95))}}
        complete = len(paired) == len(self.manifest["scenarios"])
        passed = complete and all(
            passes(q["replays"]["final"]["scores"], q["replays"]["final"]["hard_failures"])
            and not q.get("stop_reason")
            and all(q["replays"]["final"]["scores"][key] >= q["replays"]["baseline"]["scores"][key]
                    for key in ("accuracy", "directness"))
            for q in questions)
        result = {"manifest_hash": digest(self.manifest), "code": self.manifest["code"],
                  "split": self.manifest["split"], "questions": questions,
                  "planned_conversations": len(self.manifest["scenarios"]),
                  "final_setup": final, "final_setup_hash": digest(final),
                  "optimizer_usage": "unmeasured Codex account usage",
                  "runtime": "isolated fixture adapter, not the live /advisor/chat route",
                  "call_latency_seconds": latencies,
                  "promotion": "manual_only; judge calibration and independent holdout required",
                  "gate": {"passed": bool(passed), "complete": complete,
                           "threshold": .95, "judge_calibrated": False},
                  "paired_comparison": {"sample_count": len(paired),
                    "mean_delta": statistics.mean(paired) if paired else None,
                    "bootstrap_95_interval": interval,
                    "complete": complete}}
        save(self.path / "report.json", result)
        save(self.path / "final-setup.json", final)
        lines = ["# Offline advisor trajectory", "", f"Split: {result['split']}",
                 "No automatic production promotion. Codex optimizer cost is unmeasured.", ""]
        for question in questions:
            lines += [f"## {question['question']}",
                      f"Spent ${question['spent_microusd']/1e6:.6f}; reserved ${question['reserved_microusd']/1e6:.6f}.",
                      f"Stop: {question.get('stop_reason') or 'none'}; rounds {len(question['rounds'])}/3."]
            for turn_round in question["rounds"]:
                lines += [f"### Round {turn_round['number']}: {turn_round['score']:.4f}",
                          f"Components: {encoded(turn_round['scores'])}",
                          f"Failures: {turn_round['hard_failures'] or 'none'}"]
                for turn in turn_round["turns"]:
                    lines += [f"Question: {turn['question']}", f"Answer: {turn['answer']}"]
            for update in question["updates"]:
                lines += [f"### Update {update['number']} ({'retained' if update['retained'] else 'rejected/reverted'})",
                          f"Cases: {', '.join(update['trigger_cases'])}", f"Reason: {update['reason']}",
                          f"Rollback: {update.get('rollback_reason', 'none')}",
                          "```diff", update["diff"], "```"]
        lines += ["## Paired comparison", encoded(result["paired_comparison"]),
                  "Small pilots do not establish generalization. Inspect per-turn failures in report.json."]
        (self.path / "report.md").write_text("\n\n".join(lines) + "\n")
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "step", "update", "replay", "report", "reconcile", "stop"])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--setup", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--reason")
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--question")
    parser.add_argument("--call-id")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--latency-seconds", type=float)
    parser.add_argument("--env-file", type=Path, help="Local key file; only OPENROUTER_API_KEY is read")
    args = parser.parse_args(argv)
    def read(path):
        if path is None:
            raise ValueError("Required input file missing")
        return json.loads(path.read_text())
    try:
        if args.command == "init":
            Workflow.create(args.run_dir, read(args.dataset), read(args.setup),
                            candidate=read(args.candidate) if args.candidate else None)
            print("Created isolated run. No API calls made.")
            return 0
        with Workflow(args.run_dir) as flow:
            if args.command == "stop":
                if not args.question or not args.reason:
                    raise ValueError("Question and reason required")
                flow.ledger.stop(args.question, args.reason)
                flow.report()
                print("Question stopped; reserved unknown costs have not been released.")
                return 2
            if args.command == "reconcile":
                from tests.evals.chat.openrouter_transport import OpenRouterTransport
                if not args.call_id:
                    raise ValueError("Call ID required")
                try:
                    OpenRouterTransport(flow.ledger, "offline-receipt-only").reconcile(
                        args.call_id, read(args.receipt), latency_seconds=args.latency_seconds)
                finally:
                    flow.report()
                print("Provider receipt reconciled locally; no API call made.")
                return 0
            if args.command == "report":
                flow.report()
                print(f"Report: {args.run_dir / 'report.md'}")
                return 0
            if args.command == "update":
                result = flow.update(read(args.candidate), args.reason or "", args.cases or [])
            else:
                from tests.evals.chat.openrouter_transport import OpenRouterTransport
                key = os.environ.get("OPENROUTER_API_KEY")
                if not key and args.env_file:
                    from dotenv import dotenv_values
                    key = dotenv_values(args.env_file).get("OPENROUTER_API_KEY")
                if not key:
                    raise ValueError("Set OPENROUTER_API_KEY in the local environment; never put it in a manifest")
                transport = OpenRouterTransport(flow.ledger, key)
                try:
                    result = flow.step(transport) if args.command == "step" else flow.replay(transport)
                finally:
                    if hasattr(transport, "close"):
                        transport.close()
            print(encoded(result))
            if result.get("retained") is False:
                return 1
            if result.get("status") == "replay_complete" and not result["gate"]["passed"]:
                return 1 if result["gate"]["complete"] else 2
            return 3 if result.get("status") == "awaiting_update" else 0
    except (BudgetExceeded, PendingCall) as exc:
        print(f"HARD STOP: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Avoid serializing provider exceptions, which may contain request data.
        print(f"Workflow stopped ({type(exc).__name__}); inspect local checkpoints.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
