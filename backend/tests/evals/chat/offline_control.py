"""Persistent controls for the offline experiment, independent of app credentials.

Money uses integer millionths of a USD. Reserve before dispatch; unknown outcomes
remain pending until reconciled. This module does not itself execute model calls.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
from typing import Callable


WEIGHTS = {"accuracy": 10, "directness": 8, "concision": 2,
           "cost": 2, "latency": 2, "tools": 2}
CAP_MICROUSD = 1_000_000


def _number(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a finite number")
    if not math.isfinite(value):
        raise ValueError("Expected a finite number")
    return value


def normalize(raw: float) -> float:
    if not 0 <= _number(raw) <= 100:
        raise ValueError("Raw score must be in [0, 100]")
    return raw / 100


def efficiency(actual: float, target: float, upper: float) -> float:
    for value in (actual, target, upper):
        _number(value)
    if actual < 0 or not 0 <= target < upper:
        raise ValueError("Require actual >= 0 and 0 <= target < upper")
    return max(0.0, min(1.0, (upper - actual) / (upper - target)))


def aggregate(scores: dict[str, float]) -> float:
    if set(scores) != set(WEIGHTS):
        raise ValueError("Exactly six metrics are required")
    if any(not 0 <= _number(value) <= 1 for value in scores.values()):
        raise ValueError("Normalize each metric to [0, 1] first")
    return sum(scores[key] * weight for key, weight in WEIGHTS.items()) / 26


def passes(scores: dict[str, float], hard_failures: list[str]) -> bool:
    return aggregate(scores) >= .95 and not hard_failures


class InvalidTransition(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class PendingCall(RuntimeError):
    pass


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False)


def _money(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("Cost must be nonnegative integer micro-USD")


class Ledger:
    """One local checkpoint file per experiment; single active round per question.

    SQLite immediate transactions serialize reservations across processes. Reopening
    the same file preserves spend and round limits. Call IDs must be run-unique.
    """

    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY, state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, question TEXT NOT NULL,
                round INTEGER NOT NULL, reserved INTEGER NOT NULL,
                actual INTEGER, result TEXT
            );
            CREATE TABLE IF NOT EXISTS campaign_budget (
                id INTEGER PRIMARY KEY CHECK (id=1), cap INTEGER NOT NULL,
                prior INTEGER NOT NULL, provenance TEXT NOT NULL, stop_reason TEXT
            );
        """)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _state(self, question: str) -> dict:
        row = self.db.execute("SELECT state FROM questions WHERE id=?", (question,)).fetchone()
        if row is None:
            raise InvalidTransition("Unknown question")
        return json.loads(row["state"])

    def _save(self, question: str, state: dict) -> None:
        self.db.execute("UPDATE questions SET state=? WHERE id=?", (_json(state), question))

    def _calls(self, question: str) -> list[dict]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM calls WHERE question=? ORDER BY rowid", (question,))]

    def configure_campaign(self, cap: int, prior: int, provenance: str) -> None:
        _money(cap)
        _money(prior)
        if cap <= 0 or not provenance:
            raise ValueError("Campaign cap and prior-spend provenance required")
        with self._transaction():
            row = self.db.execute('SELECT * FROM campaign_budget WHERE id=1').fetchone()
            if row:
                if (row['cap'], row['prior'], row['provenance']) != (cap, prior, provenance):
                    raise InvalidTransition('Campaign budget is immutable')
                return
            if self.db.execute('SELECT 1 FROM calls').fetchone():
                raise InvalidTransition('Configure campaign before any calls')
            self.db.execute('INSERT INTO campaign_budget VALUES (1,?,?,?,?)',
                            (cap, prior, provenance, 'budget_exhausted' if prior >= cap else None))

    def campaign_summary(self) -> dict | None:
        row = self.db.execute('SELECT * FROM campaign_budget WHERE id=1').fetchone()
        if row is None:
            return None
        calls = self.db.execute('SELECT COALESCE(SUM(actual),0), COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved ELSE 0 END),0) FROM calls').fetchone()
        return dict(cap_microusd=row['cap'], prior_microusd=row['prior'],
                    spent_microusd=row['prior'] + calls[0], reserved_microusd=calls[1],
                    remaining_microusd=max(0, row['cap'] - row['prior'] - calls[0] - calls[1]),
                    provenance=row['provenance'], stop_reason=row['stop_reason'])

    def _pending(self, question: str) -> None:
        if any(call["actual"] is None for call in self._calls(question)):
            raise PendingCall("Reconcile the pending call before continuing; do not retry blindly")

    @staticmethod
    def _running(state: dict) -> None:
        if state.get("stop_reason") or state["budget_breach"]:
            raise BudgetExceeded("Conversation is hard-stopped; no retries, updates, or new rounds")

    @staticmethod
    def _halt(state: dict, reason: str) -> None:
        state["stop_reason"] = state.get("stop_reason") or reason
        if state["updates"]:
            update = state["updates"][-1]
            if update["retained"] and len(state["rounds"]) <= update["number"]:
                state["setup"] = update["before"]
                update["retained"] = False
                update["rollback_reason"] = "Unverified candidate: " + reason

    def add_question(self, question: str, setup: dict) -> None:
        if not question or not isinstance(setup, dict):
            raise ValueError("Question ID and setup object are required")
        with self._transaction():
            row = self.db.execute("SELECT state FROM questions WHERE id=?", (question,)).fetchone()
            if row:
                if json.loads(row["state"])["initial_setup"] != setup:
                    raise InvalidTransition("Cannot change the initial setup on resume")
                return
            state = dict(initial_setup=setup, setup=setup, rounds=[], updates=[],
                         active_round=None, budget_breach=False, stop_reason=None)
            self.db.execute("INSERT INTO questions VALUES (?,?)", (question, _json(state)))

    def start_round(self, question: str) -> int:
        with self._transaction():
            state = self._state(question)
            self._running(state)
            self._pending(question)
            completed = len(state["rounds"])
            if state["active_round"] is not None or completed >= 3:
                raise InvalidTransition("Round already active or three rounds completed")
            if len(state["updates"]) != completed:
                raise InvalidTransition("Record one update decision before the next round")
            state["active_round"] = completed + 1
            state["active_setup"] = state["setup"]
            self._save(question, state)
            return completed + 1

    def reserve(self, question: str, call_id: str, maximum_microusd: int) -> None:
        _money(maximum_microusd)
        if not call_id or maximum_microusd == 0:
            raise ValueError("Call ID and a positive conservative cost bound are required")
        with self._transaction():
            state = self._state(question)
            self._running(state)
            self._pending(question)
            if state["active_round"] is None:
                raise InvalidTransition("Start a round before dispatching calls")
            if self.db.execute("SELECT 1 FROM calls WHERE id=?", (call_id,)).fetchone():
                raise InvalidTransition("Call already completed; read its cached result")
            spent = sum(call["actual"] for call in self._calls(question))
            campaign = self.campaign_summary()
            campaign_denied = campaign and (campaign['stop_reason'] or
                maximum_microusd > campaign['remaining_microusd'])
            denied = bool(campaign_denied) or spent + maximum_microusd > CAP_MICROUSD
            if denied:
                if campaign_denied:
                    self.db.execute("UPDATE campaign_budget SET stop_reason=COALESCE(stop_reason,'budget_exhausted') WHERE id=1")
                self._halt(state, "campaign_budget_exhausted" if campaign_denied else "budget_exhausted")
                self._save(question, state)
            else:
                self.db.execute("INSERT INTO calls VALUES (?,?,?,?,NULL,NULL)",
                                (call_id, question, state["active_round"], maximum_microusd))
        # Raise after commit so the terminal state survives exception handling/restart.
        if denied:
            raise BudgetExceeded("Persistent budget stop: the available allowance cannot cover this call")

    def dispatch(self, question: str, call_id: str, maximum_microusd: int,
                 provider_call: Callable[[], tuple[int, dict]]) -> dict:
        """The provider callable is never entered unless reservation succeeds.

        Caller supplies a bounded single-call transport, not an SDK with hidden
        retries. Exceptions leave the reservation pending for reconciliation.
        """
        self.reserve(question, call_id, maximum_microusd)
        actual, result = provider_call()
        self.settle(call_id, actual, result)
        return result

    def settle(self, call_id: str, actual_microusd: int, result: dict) -> None:
        """Persist provider-confirmed cost and response, including an overrun if one occurs."""
        _money(actual_microusd)
        serialized = _json(result)
        with self._transaction():
            call = self.db.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
            if call is None or call["actual"] is not None:
                raise InvalidTransition("Only a pending call may be settled")
            self.db.execute("UPDATE calls SET actual=?, result=? WHERE id=?",
                            (actual_microusd, serialized, call_id))
            breached = actual_microusd > call["reserved"]
            campaign = self.campaign_summary()
            if campaign and (breached or campaign['spent_microusd'] >= campaign['cap_microusd']):
                self.db.execute("UPDATE campaign_budget SET stop_reason=COALESCE(stop_reason,?) WHERE id=1",
                                ('reservation_exceeded' if breached else 'budget_exhausted',))
            spent = sum(item["actual"] or 0 for item in self._calls(call["question"]))
            if breached or spent >= CAP_MICROUSD:
                state = self._state(call["question"])
                state["budget_breach"] = breached or state["budget_breach"]
                self._halt(state, "reservation_exceeded" if breached else "budget_exhausted")
                self._save(call["question"], state)
        if breached:
            raise BudgetExceeded("Provider exceeded reserved bound; recorded cost and blocked further calls")

    def cached(self, call_id: str) -> dict | None:
        row = self.db.execute("SELECT result FROM calls WHERE id=?", (call_id,)).fetchone()
        return json.loads(row["result"]) if row and row["result"] is not None else None

    def finish_round(self, question: str, scores: dict[str, float],
                     hard_failures: list[str], turns: list[dict], details: dict | None = None) -> None:
        score = aggregate(scores)
        hard_failures = list(hard_failures)
        if not turns or any(not turn.get("question") or not turn.get("answer") for turn in turns):
            hard_failures.append("incomplete_transcript")
        with self._transaction():
            state = self._state(question)
            self._pending(question)
            if state["active_round"] is None or state.get("active_replay"):
                raise InvalidTransition("No active round")
            state["rounds"].append(dict(
                number=state["active_round"], setup=state.get("active_setup", state["setup"]), scores=scores,
                score=score, hard_failures=hard_failures, turns=turns, details=details or {},
                passed=passes(scores, hard_failures) and not state["budget_breach"]
                and not state.get("stop_reason")))
            if hard_failures and state["updates"]:
                update = state["updates"][-1]
                if update["number"] == state["active_round"] - 1:
                    state["setup"] = update["before"]
                    update["retained"] = False
                    update["rollback_reason"] = "; ".join(hard_failures)
            state["active_round"] = None
            self._save(question, state)

    def rollback_update(self, question: str, reason: str) -> None:
        with self._transaction():
            state = self._state(question)
            if not state["updates"] or state["active_round"] is not None:
                raise InvalidTransition("No evaluated update to roll back")
            update = state["updates"][-1]
            if len(state["rounds"]) != update["number"] + 1:
                raise InvalidTransition("Update has not been evaluated")
            state["setup"] = update["before"]
            update["retained"] = False
            update["rollback_reason"] = reason
            self._save(question, state)

    def stop(self, question: str, reason: str) -> None:
        with self._transaction():
            state = self._state(question)
            self._halt(state, reason)
            self._save(question, state)

    def start_replay(self, question: str, label: str) -> None:
        if label not in {"baseline", "final"}:
            raise ValueError("Only frozen baseline/final replays are permitted")
        with self._transaction():
            state = self._state(question)
            self._running(state)
            self._pending(question)
            if state["active_round"] is not None or label in state.get("replays", {}):
                raise InvalidTransition("Replay already active or completed")
            state["active_round"] = 0
            state["active_replay"] = label
            self._save(question, state)

    def finish_replay(self, question: str, result: dict) -> None:
        aggregate(result["scores"])
        with self._transaction():
            state = self._state(question)
            self._pending(question)
            label = state.get("active_replay")
            if not label:
                raise InvalidTransition("No active replay")
            state.setdefault("replays", {})[label] = result
            state["active_replay"] = None
            state["active_round"] = None
            self._save(question, state)

    def apply_update(self, question: str, setup: dict, reason: str,
                     trigger_cases: list[str], diff: str, validated: bool,
                     tool_oracles: dict | None = None) -> None:
        """Record an external Codex edit or no-op; rejected edits still consume a slot.

        This records validation evidence supplied by the operator. It is not a
        sandbox or an independent validator for generated code.
        """
        if not isinstance(setup, dict) or not reason or not trigger_cases or not diff:
            raise ValueError("Update requires setup, reason, triggering cases, and diff/no-op explanation")
        if type(validated) is not bool:
            raise ValueError("Validation must be a boolean")
        with self._transaction():
            state = self._state(question)
            self._running(state)
            rounds, updates = len(state["rounds"]), len(state["updates"])
            if state["active_round"] is not None or rounds not in (1, 2) or updates != rounds - 1:
                raise InvalidTransition("Updates are allowed once after round 1 and once after round 2")
            state["updates"].append(dict(number=updates + 1, reason=reason,
                trigger_cases=trigger_cases, diff=diff, before=state["setup"],
                proposed=setup, retained=validated))
            if validated:
                state["setup"] = setup
                if tool_oracles is not None:
                    self.db.execute("UPDATE artifacts SET payload=? WHERE name='tool_oracles'",
                                    (_json(tool_oracles),))
            self._save(question, state)

    def summary(self, question: str) -> dict:
        with self._transaction():
            state = self._state(question)
            calls = self._calls(question)
            spent = sum(call["actual"] or 0 for call in calls)
            reserved = sum(call["reserved"] for call in calls if call["actual"] is None)
            return dict(state, question=question, cap_microusd=CAP_MICROUSD,
                        spent_microusd=spent, reserved_microusd=reserved,
                        remaining_microusd=max(0, CAP_MICROUSD - spent - reserved),
                        call_count=len(calls), pending_call_ids=[
                            call["id"] for call in calls if call["actual"] is None])
