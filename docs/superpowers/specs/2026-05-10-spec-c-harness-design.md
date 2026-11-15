# Spec C Harness — Delivery Design

> **Companion to:** `2026-05-09-eval-chat-quality-spec.md` (the architectural spec).
> This doc is the *delivery shape*: what we build, in what order, with what file-by-file deltas.
> The architectural spec answers *what good looks like*; this doc answers *how it lands*.

---

## 1. Background

The architectural spec for Spec C (chat-advisor quality eval) is unusually prescriptive: file
layout (§13), dataset schema (§3), run-protocol pseudocode (§6.1), all 26 scenario ids + intents
(§8), one full rubric body (`portfolio_attribution_v1`, §4.2), failure-mode taxonomy (§7), and
versioning rules (§10) are all specified.

What is NOT in the spec:
- The integration choices for *how* the harness reaches the live `/advisor/chat` endpoint
  (eval-mode auth, mock plumbing).
- The *delivery sequence* — Spec C lands as one big harness or as phased slices.
- The 3 remaining rubric bodies (`conflict_pushback_v1`, `omission_holistic_v1`,
  `narration_math_cite_v1`) — listed by criterion-id only in §4.3 with the body authoring marked
  as the largest follow-up.
- The 23 remaining new scenario JSONL bodies (§8 lists ids + one-line intents only).
- Per-PR CI sampling automation (§9.3 describes the cadence rule, not the workflow).

This delivery design fills those gaps and sequences the work into five phases.

## 2. What Spec A already shipped (inheritance map)

Commit `d51e4a5` ("test(eval): implement Spec A frontend behavior suite") landed pieces that
Spec C can reuse rather than rebuild. Audit before designing:

| Piece | Status | Spec C consequence |
|---|---|---|
| `GET /eval/health` (gated on `EVAL_MOCKS=1`) | **Exists** in `backend/app/main.py:147–174`. Inspects whether `fetch_fred_series`, `parse_investment_statement`, and Plaid client have been patched. | Phase 1 reuses; **does not re-add**. |
| `EVAL_MOCKS=1` env-var gate | **Exists** (read by `main.py:147`). | Phase 1 reuses. |
| `install_mocks()` at uvicorn startup | **Does NOT exist.** `/eval/health` only *checks* mock state — Spec A's tests live with `fred_mocked: false` because they don't actually monkey-patch the running process. | Phase 2.2 must add this. |
| Auth bypass (`X-Eval-User-Id` header) | **Does NOT exist.** Spec A logs in as a real Supabase user (`eval-a@test.local`) via the UI for storageState. | Phase 1 must add this — Spec C is HTTP-driven, no browser. |
| Seed CLI runner | **Exists** at `backend/tests/evals/shared/seed_runner.py` with `single_brokerage` fixture, user id `u-eval-a`. | Phase 1 reuses pattern. Spec C adds new fixtures alongside. |
| `Seed` class | **Exists** at `backend/tests/evals/shared/seed.py`. | Phase 1 reuses unchanged. |

**Convention alignment:** Spec A uses string user ids (`u-eval-a`), not UUIDs. Spec C follows
suit with `EVAL_USER_ID = "u-eval-c"`. The auth bypass returns this string verbatim; downstream
handlers compare it as a string against the `user_id` column (also TEXT in the schema).

## 3. Prerequisites and prior decisions

Two integration decisions made during brainstorming, recorded here:

**Decision 1 — Eval-mode auth bypass instead of password login.**
The harness needs to make `/advisor/chat` think a request is from a known `user_id`. Three
options were considered:

| Option | Choice rationale |
|---|---|
| Sign in with email+password | Rejected: project user logs in via GitHub OAuth; no password exists. |
| Mint a JWT locally with the Supabase JWT secret | Rejected: leaks the JWT secret into `backend/.env`. |
| **EVAL_MOCKS gate + `X-Eval-User-Id` header bypass** | **Chosen**: surgical (~15 lines in `auth/middleware.py`), no extra secret exposed, gated on env var that's never set in prod. |

**Decision 2 — Synthetic UUID, not the real user.**
The seeded fixtures write into `accounts`/`goals`/`transactions` under a synthetic UUID
(`EVAL_USER_ID = 00000000-0000-0000-0000-000000000001`) so that eval runs never touch the
project owner's real data. Nothing in Supabase auth needs to exist for this UUID — the bypass
skips JWT validation, the Seed API just upserts rows under that user_id.

**Out-of-scope decisions** (deferred):
- Latency/throughput benchmarking (Spec C §1 explicit non-goal).
- Production cost monitoring (separate dashboard concern).
- Spec A frontend eval, Spec B backend correctness eval (separate specs).
- LLM-driven scenario authoring (manual per spec).
- Auto-retry on judge JSON failures (explicitly forbidden per spec §11.7).

## 4. Phases at a glance

Five phases, each shipped as its own implementation plan. Sequencing is by dependency, not by
estimated effort.

| Phase | Deliverable | Depends on | Unblocks |
|---|---|---|---|
| **1** | MVP loop end-to-end (1 rubric, 11 scenarios incl. 10 legacy migrated) | nothing | everything |
| **2.2** | FRED / yfinance / Plaid mocks + `/eval/health` flag accuracy | Phase 1 | macro-context and stale-data scenarios in 2.1 |
| **2.1** | 3 remaining rubric bodies + 25 remaining scenarios | 2.2 (for some scenarios) | release-gating Spec C runs; 2.3 |
| **2.3** | Inter-judge agreement (`--check-agreement`, Spearman ρ) | 2.1 (rubrics under test) | rubric refinement loop |
| **2.4** | Per-PR CI sampling (GitHub Action + diff-aware tag inference) | 2.1 + 2.3 | release-gating-on-PR |

Phase 1 lands first because it surfaces every integration risk on the cheapest possible scope.
Phase 2.2 lands next because mock plumbing is a backend prerequisite for ~¼ of 2.1's scenarios.
Phase 2.1 is the largest authoring effort. Phases 2.3 and 2.4 then layer on top.

---

## 5. Phase 1 — MVP loop

### 5.1 Scope

- **1 fully-bodied rubric:** `portfolio_attribution_v1` — already authored in spec §4.2,
  copied verbatim into `rubrics.yaml`.
- **1 stub rubric for legacy migration:** `general_transaction_v1` — three criteria
  (`contains_expected_substring`, `cites_concrete_number`, `does_not_invent_data`). Tagged
  `[LEGACY]` per spec §4.3; failures don't gate releases.
- **1 new portfolio attribution scenario:** `portfolio.attribution.basic` — no FRED mock
  dependency; the unattributed-bucket criterion auto-scores 1.0 when residual ≤ $100 per spec
  §4.2. The other two attribution scenarios (`unattributed`, `macro_context`) depend on FRED
  override, so they move to Phase 2.1 after mocks land.
- **10 migrated legacy rows** from existing `backend/tests/evals/dataset.jsonl`, translated
  to v3 format per spec §12.1.

**Total run shape:** 11 scenarios × N=3 = 33 advisor calls + ~33 judge calls. Default budget
cap 100¢ (spec §9.1 estimates ~$0.25 for this size).

### 5.2 Backend changes (auth bypass only — `/eval/health` already exists)

`backend/app/auth/middleware.py` is currently a synchronous JWT-validation path:

```python
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> dict:
    token = credentials.credentials
    try:
        user = _supabase_client().auth.get_user(token)
        return user.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
```

Phase 1 prepends an eval-mode short-circuit. Switch the dependency to take the full `Request`
so the bypass can read the `X-Eval-User-Id` header without breaking the existing call sites:

```python
from fastapi import Request
from types import SimpleNamespace
import os, logging

EVAL_MOCKS_ENABLED = os.getenv("EVAL_MOCKS") == "1"
log = logging.getLogger(__name__)

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> dict:
    if EVAL_MOCKS_ENABLED:
        eval_user_id = request.headers.get("X-Eval-User-Id")
        if eval_user_id:
            log.warning("eval-mode auth bypass active for user %s", eval_user_id)
            return SimpleNamespace(id=eval_user_id,
                                   email=f"{eval_user_id}@suan-pan.eval")
    # existing JWT validation path unchanged
    ...
```

**Why `SimpleNamespace`:** the existing handler returns `user.user` (a Supabase `User` object).
Downstream code accesses `.id` and sometimes `.email`. `SimpleNamespace` is the smallest stub
that satisfies this without creating a fake `User` class.

**Safety property:** `EVAL_MOCKS` is read once at module import. Production deploys must not
set it. The bypass branch is unreachable when the env var is unset — verified by
`test_eval_mocks_gate.py` in Phase 2.2.

`/eval/health` already exists and reports per-mock state; no change needed in Phase 1.

### 5.3 Harness directory

```
backend/tests/evals/chat/
├── __init__.py                          # exports EVAL_USER_ID
├── dataset.jsonl                        # header + 13 rows
├── rubrics.yaml                         # 2 rubrics
├── judge.py                             # Anthropic SDK wrapper
├── run_eval.py                          # main entry (refactored from parent dir)
├── seeds/
│   ├── __init__.py
│   └── portfolio_attribution.py         # 1 seed factory for portfolio.attribution.basic
├── reports/
│   └── .gitignore                       # *\n!.gitignore
└── test_dataset_shape.py                # pytest sanity
```

### 5.4 Module responsibilities

**`__init__.py`**
```python
# Aligns with Spec A convention (u-eval-a). Spec-letter suffix isolates
# fixture data per eval suite so concurrent A/B/C runs don't collide.
EVAL_USER_ID = "u-eval-c"
EVAL_HEADERS = {"X-Eval-User-Id": EVAL_USER_ID}
```

**`judge.py`** — exports:
- `load_rubric(rubric_id: str, rubrics_path: Path) -> dict`
- `score_reply(rubric, user_messages, advisor_reply, tool_calls) -> dict[str, float]`
- `check_forbidden_signals(advisor_reply, forbidden_signals, judge_model) -> bool`
- Internal: `_anthropic_client()` lazily constructed from `ANTHROPIC_API_KEY`.
- Malformed JSON: raises `JudgeMalformedJSON`; runner catches and tags `[JUDGE-LOW-CONFIDENCE]`,
  no retry per spec §11.7.

**`run_eval.py`** — main entry. CLI flags:
- `--tags <comma-list>` — filter scenarios by tag
- `--limit <n>` — cap scenario count
- `--max-cost-cents <n>` — budget cap (default 100)
- `--dry-run` — validate dataset shape only
- `--report-out <path>` — override default report path

Drives the spec §6.1 pseudocode loop verbatim. Writes JSON to
`backend/tests/evals/chat/reports/report-{ts}-{sha}.json` and Markdown summary to
`docs/test-reports/eval-c-{ts}-{sha}.md`.

**`seeds/portfolio_attribution.py`** — Phase 1 exposes one function. Pattern matches Spec A's
`backend/tests/evals/shared/seed_runner.py` so the same `Seed` builder API is used everywhere.
```python
def single_account_2_holdings(seed: Seed) -> Seed: ...
```
Returns a configured `Seed` ready for `.apply(supabase_client)`. Phase 2.1 adds
`attribution_with_unattributed` and `attribution_macro_context` once the FRED mock exists.

**`test_dataset_shape.py`** — pytest:
- Every dataset row matches v3 schema (required fields present, types correct).
- Every `judge_prompt_id` resolves to a rubric in `rubrics.yaml`.
- Every rubric's criterion ids cover all `expected_signals.id` referenced by scenarios using it.
- Weights per scenario sum to 1.0 (±1e-6).
- Scenario ids are unique.

### 5.5 SSE chat session and tool-call capture

**Reality check on the spec.** Spec §6.2 pseudocode assumed SSE events of shape
`{"type": "tool_call", "name": ..., "args": ..., "result_data": ...}`. The actual stream from
`backend/app/advisor/router.py` only emits `{"tool_call": "<name>", "status": "running"|"done"}`
— *names only, no args, no results*. The judge needs both args (for `match_check`) and
results (to score `cites_concrete_number` and similar criteria).

**Resolution: server-side tool-call recorder, exposed via an eval-mode endpoint.**

1. **`backend/app/eval/context.py`** (Phase 1 stub; expanded in 2.2): an in-process dict
   `_eval_tool_calls: dict[session_id, list[ToolCallRecord]]`. Helper:
   ```python
   def record_tool_call(session_id: str, name: str, args: dict, result_data: object) -> None:
       if not EVAL_MOCKS_ENABLED:
           return  # no-op in prod
       _eval_tool_calls.setdefault(session_id, []).append({
           "name": name, "args": args, "result_data": result_data,
       })
   ```

2. **`backend/app/advisor/router.py`** (~5-line addition in the tool-execution branch around
   line 708 after `result_data` is parsed): call `record_tool_call(session_id, fc.name,
   args, result_data)`. In production the helper short-circuits; in eval mode it records.

3. **`GET /eval/tool_calls/{session_id}`** (added inline in `main.py` next to `/eval/health`,
   gated on `EVAL_MOCKS=1`): returns `_eval_tool_calls[session_id]` or `[]`.

4. **`ChatSession.send()`** in the harness: parses the SSE for `text` and `session_id`;
   after the stream closes, calls `GET /eval/tool_calls/{session_id}` to fetch the structured
   tool-call log; returns `(reply_text, tool_calls)`.

```python
class ChatSession:
    def __init__(self, base_url: str, user_id: str):
        self._client = httpx.Client(
            base_url=base_url,
            headers={"X-Eval-User-Id": user_id},
            timeout=60.0,
        )
        self._session_id: str | None = None

    def send(self, msg: dict) -> tuple[str, list[dict]]:
        payload = {"message": msg["content"]}
        if self._session_id:
            payload["session_id"] = self._session_id
        reply_text = ""
        with self._client.stream("POST", "/advisor/chat", json=payload) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                if "text" in data:
                    reply_text += data["text"]
                elif "session_id" in data:
                    self._session_id = data["session_id"]
        # Fetch structured tool calls captured server-side
        if self._session_id:
            r = self._client.get(f"/eval/tool_calls/{self._session_id}")
            tool_calls = r.json() if r.status_code == 200 else []
        else:
            tool_calls = []
        return reply_text, tool_calls
```

**Why server-side recording instead of richer SSE events:** changing the SSE shape would
ripple into the frontend renderer. The recorder is a no-op in production and an in-memory
appended list in eval mode — no schema changes, no frontend impact.

### 5.6 Migrating the existing 10-row dataset

Existing `backend/tests/evals/dataset.jsonl` rows look like:
```json
{"id": "E01", "message": "Show me my transactions last week",
 "expected_tools": ["list_transactions"], "must_contain": ["transaction"]}
```

Migration translates each to v3:
```json
{"id": "E01", "dataset_version": "v3", "tags": ["legacy", "transactions"],
 "setup": {"seed_id": "default_legacy_user", "fred_mock": null, "extra_sql": null},
 "messages": [{"role": "user", "content": "Show me my transactions last week"}],
 "expected_tools": [{"name": "list_transactions", "args_must_contain": {}}],
 "forbidden_tools": [],
 "expected_signals": [
   {"id": "contains_expected_substring", "weight": 0.5, "required": false},
   {"id": "cites_concrete_number", "weight": 0.25, "required": false},
   {"id": "does_not_invent_data", "weight": 0.25, "required": true}
 ],
 "forbidden_signals": [],
 "judge_prompt_id": "general_transaction_v1",
 "n_runs": 3, "pass_threshold": 0.8}
```

The `must_contain` substring becomes a `contains_expected_substring` criterion in the
`general_transaction_v1` rubric. The substring itself is passed to the judge as part of the
criterion description, generated at dataset-build time.

After migration:
- `backend/tests/evals/dataset.jsonl` deleted (its content moved + transformed).
- `backend/tests/evals/run_eval.py` deleted (refactored content moved to `chat/run_eval.py`).
- `backend/tests/evals/test_dataset_shape.py` deleted (Spec C's own test is more thorough;
  the parent test was for the old format).

### 5.7 Dependencies and env

`backend/requirements.txt` adds:
- `anthropic` — judge SDK
- `pyyaml` — rubric loader

`backend/.env.example` documents:
- `EVAL_MOCKS=1` — gates eval-mode behavior
- `ANTHROPIC_API_KEY` — judge

Repo `.gitignore` adds:
- `backend/tests/evals/chat/reports/*.json`

### 5.8 Pre-flight checks before any run

1. `curl -fsS http://localhost:8000/eval/health` → `eval_mocks: true`
2. `ANTHROPIC_API_KEY` set
3. `GOOGLE_API_KEY` set (subject)
4. `backend/tests/evals/chat/{dataset.jsonl,rubrics.yaml,run_eval.py,judge.py}` exist
5. Dataset shape test passes (`pytest test_dataset_shape.py`)

If any fails, runner exits non-zero with a clear message; the agent file (`.claude/agents/eval-chat-quality.md`) writes a "not ready" report.

---

## 6. Phase 2.2 — EVAL_MOCKS plumbing

### 6.1 What's already done (don't rebuild)

- `EVAL_MOCKS=1` env-var gate — exists.
- `GET /eval/health` endpoint — exists, inspects `fetch_fred_series`/`parse_investment_statement`/
  Plaid-client modules for monkey-patch state.

### 6.2 What Phase 2.2 actually adds

Of the 25 remaining scenarios in 2.1, the following depend on mock infrastructure:
- `portfolio.attribution.unattributed` — needs FRED override
- `portfolio.attribution.macro_context` — needs FRED override
- `conflict.snapshot_vs_snapshot` — needs `extra_sql` to inject inconsistent timestamps
- `pushback.*` scenarios involving stale data — need yfinance mock to control prices
- Plaid sync scenarios — none in the §8 inventory today, but the mock plumbing is added now
  to unblock future scenarios without a second backend round-trip

Phase 1 sidesteps these (the 1 portfolio attribution MVP scenario uses only the seed + the
attribution tool, with no FRED dependency). Phase 2.1 cannot land all 25 scenarios without
2.2 behind it.

### 6.3 New backend files

```
backend/app/eval/
├── __init__.py
├── mocks.py        # install_mocks() — patches FRED, yfinance, Plaid (called from lifespan)
└── context.py      # per-request mock-override store (contextvar)
```

`/eval/health` already lives in `main.py` and reads from these patched modules; Phase 2.2
just makes the patches exist for it to detect. No new endpoint file needed for `/eval/health`
itself; one new endpoint (`POST/DELETE /eval/context`) is added inline in `main.py` next to
`/eval/health`.

### 6.4 Mock installation

`install_mocks()` is called from FastAPI's `lifespan` startup hook *only* when `EVAL_MOCKS=1`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("EVAL_MOCKS") == "1":
        from app.eval.mocks import install_mocks
        install_mocks()
    yield
```

Each mock is a function-level patch on the call site (not a global httpx interceptor), so
unmocked code paths remain unaffected:

- **FRED:** patches `app.engine.macro.fetch_fred_series` (or wherever the call lives) to read
  from `app.eval.context.get_fred_overrides()`.
- **yfinance:** patches the yfinance call site to return canned daily prices from a fixture
  file `backend/app/eval/fixtures/prices.json`.
- **Plaid:** patches the Plaid client wrapper to return fixture transactions/accounts.

### 6.5 Per-request mock-override channel

Spec §3.1 lets each scenario override FRED values via `setup.fred_mock`. The runner pushes
those overrides to the backend before each run via:

```
POST /eval/context
{"fred": {"DGS10": -8.2}, "extra_sql_applied": "scenarios/conflict_snapshot_vs.sql"}
```

This endpoint:
- Gated identically on `EVAL_MOCKS=1`
- Stores overrides in a `contextvars.ContextVar` keyed by `EVAL_USER_ID`
- Cleared at session end via `DELETE /eval/context`

`/eval/health` reports the current flag state (`fred_mocked: true`, `plaid_mocked: true`, etc.)
based on whether `install_mocks()` registered each patch successfully at startup.

### 6.6 Harness self-tests added in 2.2

- `test_eval_mocks_gate.py` — `/eval/health` returns 404 when `EVAL_MOCKS` unset; the bypass
  branch in `auth/middleware.py` does not execute when env var unset.
- `test_seed_determinism.py` — same `seed_id` applied twice produces identical `AppliedSeed`.
- `test_mock_overrides.py` — POST `/eval/context` then call `/engine/portfolio_attribution`
  → result reflects the FRED override.

---

## 7. Phase 2.1 — Remaining rubrics + scenarios

### 7.1 Three new rubric bodies

| Rubric | Covers | Criteria (from spec §4.3) |
|---|---|---|
| `conflict_pushback_v1` | §8.1 conflict (5) + §8.2 pushback (6) = 11 scenarios | `surfaces_conflict_before_advising`, `cites_ground_truth_figure`, `declines_to_endorse_bad_idea`, `offers_alternative` |
| `omission_holistic_v1` | §8.4 omission (3) | `mentions_expected_gap`, `does_not_invent_data`, `stays_grounded_in_context`, `asks_clarifying_question_when_appropriate` |
| `narration_math_cite_v1` | §8.3 math-narration (4) + §8.5 portfolio precision (5 of 8) = 9 | `cites_tool_number`, `does_not_round_aggressively`, `attributes_source`, `no_invented_figure` |

### 7.2 Authoring bar (spec §4.3, repeated for delivery)

Each rubric body is "complete" when:

1. `judge_system_prompt` is fully written, instructing the judge to return JSON only and
   describing what the judge sees (USER MESSAGE / ADVISOR REPLY / TOOL CALLS / CRITERIA),
   following the structure shown in `portfolio_attribution_v1` §4.2.
2. Each criterion has a one-sentence `description` written from "this criterion passes if…"
   perspective. The description must NOT reference SYSTEM_PROMPT wording (anti-pattern §11.3).
3. Manual spot-check: at least 3 known-good and 3 known-bad replies scored by the judge,
   manually validated. Spot-check transcripts saved under `backend/tests/evals/chat/spot_checks/`.
4. Inter-judge agreement (Spearman ρ ≥ 0.8) confirmed on a 5-scenario subset using both
   Haiku and Sonnet (this is why 2.3 is sequenced near 2.1).

A rubric that fails any of these stays `[LEGACY]`-tagged and excluded from release-gating
until refined.

### 7.3 25 new scenario JSONL bodies

Inventory from spec §8 (already named):
- §8.1 conflict (5): `conflict.snapshot_vs_user`, `conflict.snapshot_vs_snapshot`,
  `conflict.snapshot_vs_portfolio`, `conflict.self.multi_turn`, `conflict.ambiguous_reference`
- §8.2 pushback (6): `pushback.emergency_fund_into_stock`, `pushback.401k_loan_for_mortgage`,
  `pushback.grief_irreversible`, `pushback.whole_life_insurance`,
  `pushback.concentration_double_down`, `pushback.early_401k_withdrawal`
- §8.3 math-narration (4): `narration.cites_compound_interest`, `narration.cites_debt_avalanche`,
  `narration.cites_marginal_tax`, `narration.cites_attribution_buckets`
- §8.4 omission (3): `omission.no_employer_match`, `omission.no_emergency_fund`,
  `omission.dependents_no_529`
- §8.5 portfolio (7 remaining beyond Phase 1's 1): `portfolio.attribution.unattributed`,
  `portfolio.attribution.macro_context`, `portfolio.exposure.precision`,
  `portfolio.exposure.concentration`, `portfolio.holdings.precision`,
  `portfolio.holdings.zero_position`, `portfolio.read_only.fake_action`

Each row carries the v3 schema fields per spec §3.1, drawn from a per-scenario seed factory.

### 7.4 Seed factory expansion

`backend/tests/evals/chat/seeds/` grows to:

```
seeds/
├── __init__.py
├── portfolio_attribution.py    # Phase 1
├── portfolio_holdings.py       # Phase 2.1
├── portfolio_exposure.py
├── conflict.py                 # snapshot vs user/snapshot/portfolio fixtures
├── pushback.py                 # emergency-fund-as-investment, etc.
├── omission.py                 # no-match, no-EF, no-529 fixtures
└── narration.py                # math-narration fixtures (compound interest, debt avalanche, etc.)
```

Factories live next to the harness, not in `shared/`, so Spec C can iterate on its own
fixtures without touching Spec B.

### 7.5 Cost at full scope

36 scenarios (11 from Phase 1 + 25 from 2.1) × 3 runs = 108 advisor calls + ~108 judge calls.
Spec §9.1 estimates $0.55–$3 per full run. Default budget cap raises to **500¢** (per spec
§9.2) once Phase 2.1 lands.

---

## 8. Phase 2.3 — Inter-judge agreement

### 8.1 What it does

When invoked with `--check-agreement`, the runner:
1. Picks 5 random scenarios from the run set (deterministic given the seeded RNG; same 5 each
   time unless `--check-agreement-seed=<n>` overrides).
2. Re-scores each with both `claude-haiku-4-5-20251001` (default judge) and
   `claude-sonnet-4-6` (agreement judge).
3. Computes Spearman ρ per criterion, per rubric.
4. Reports per-rubric ρ in the run header (spec §5.5 format).
5. Emits a warning + names the rubric for refinement if any rubric scores ρ < 0.8.
   Does NOT fail the run — agreement is advisory.

### 8.2 No scipy dependency

Spearman ρ is computed inline in `backend/tests/evals/chat/agreement.py`:

```python
def spearman(a: list[float], b: list[float]) -> float:
    """Standard Spearman rank correlation; no external dep."""
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    rank_a = _rank(a); rank_b = _rank(b)
    n = len(a)
    d_squared_sum = sum((rank_a[i] - rank_b[i]) ** 2 for i in range(n))
    return 1 - (6 * d_squared_sum) / (n * (n * n - 1))
```

`scipy` is a heavy dep; ten lines of well-tested formula avoids adding it.

### 8.3 Cadence

Triggered manually via `--check-agreement` OR every 10th full run automatically. The runner
tracks invocation count in `backend/tests/evals/chat/.run_count` (gitignored).

### 8.4 Cost impact

5 scenarios × 4 criteria × 2 judges = 40 extra judge calls per agreement check. ~$0.05 added.
Budget cap covers it.

---

## 9. Phase 2.4 — Per-PR CI sampling

### 9.1 Trigger

GitHub Action `.github/workflows/eval-chat-pr.yml` with **`workflow_dispatch` manual approval
only** — auto-running on every PR push would burn budget on draft commits.

### 9.2 Diff-aware tag inference

`scripts/eval-chat-pr.sh` reads `git diff --name-only origin/main...HEAD` and infers tags:

| Touched files | Inferred tags |
|---|---|
| `backend/app/advisor/context.py` (SYSTEM_PROMPT or context builder) | `pushback,portfolio.attribution` |
| `backend/app/mcp/tools.py` | per modified function name; portfolio tools → `portfolio` |
| `backend/app/advisor/router.py` (context assembly) | `conflict,omission` |
| `backend/app/engine/*.py` only | skip Spec C (Spec B's territory) |
| Nothing advisor-related | skip Spec C, post "no chat-eval-relevant changes" comment |

### 9.3 Output

PR comment posted by the workflow contains:
- Scenario distribution table (3/3 / 2/3 / 1/3 / 0/3 counts)
- Flaky list (scenarios with 1/3 or 2/3 pass)
- Forbidden-signal hits (release-blockers, surfaced prominently)
- Top-5 lowest-scoring scenarios with judge breakdown
- Tag-inference summary (which subset ran and why)

### 9.4 Secrets and cost

- `ANTHROPIC_API_KEY` and `EVAL_GOOGLE_API_KEY` (separate from prod Google key for billing
  isolation) as repo secrets.
- Default `--max-cost-cents 200` for PR runs; full-run promotion via `gh workflow run --field
  max-cost-cents=500`.
- The cost cap is a runner-side circuit breaker, not an account-level Anthropic limit. If
  hit, the runner aborts non-zero and lists un-run scenario ids in the PR comment.

---

## 10. Cross-cutting concerns

### 10.1 Versioning header in every report

Every JSON and Markdown report begins with a six-field versioning header (spec §10). Two
reports are comparable only if all six fields match.

```
Run date:              2026-05-10T14:32:00Z
Dataset version:       v3 (from JSONL header row)
Judge prompt version:  portfolio_attribution_v1@<sha8>
System prompt version: sha256:<first-12-chars>
Subject model:         gemini-2.5-flash-preview-04-17 / temp 1.0
Judge model:           claude-haiku-4-5-20251001 / temp 0
Suan-Pan git SHA:      <full sha>
```

`SP_VERSION = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]` per spec §10.

### 10.2 Failure-mode taxonomy

All tags from spec §7 are derived programmatically by the runner from criterion scores +
tool-call match results. Tags are never assigned by the judge — the judge assigns scores; the
runner assigns tags. This separation is enforced by code, not convention.

### 10.3 Harness self-tests (cumulative across phases)

| Test | Phase | Asserts |
|---|---|---|
| `test_dataset_shape.py` | 1 | schema, weights, uniqueness, rubric-id resolution |
| `test_eval_mocks_gate.py` | 2.2 | `/eval/health` 404 without env var; bypass inert |
| `test_seed_determinism.py` | 2.2 | same seed_id → same AppliedSeed |
| `test_mock_overrides.py` | 2.2 | per-request mock context flows through |
| `test_judge_unreachable.py` | 1 | judge 5xx → tag, no retry |
| `test_judge_malformed_json.py` | 1 | malformed response → `[JUDGE-LOW-CONFIDENCE]`, no retry |
| `test_agreement_spearman.py` | 2.3 | inline Spearman ρ matches scipy on golden inputs |
| `test_diff_to_tags.py` | 2.4 | path patterns map to expected tag sets |

### 10.4 Reports

- JSON: `backend/tests/evals/chat/reports/report-{ts}-{sha}.json` (gitignored, never deleted —
  trend dataset for prompt-drift detection).
- Markdown: `docs/test-reports/eval-c-{ts}-{sha}.md` (committed; ≤ 800 lines per agent file).

---

## 11. Out of scope (this design)

- Latency / throughput benchmarking (Spec C §1 explicit non-goal).
- Production monitoring dashboards.
- Spec A frontend eval, Spec B backend correctness eval.
- LLM-driven scenario authoring tools.
- Auto-retry on judge JSON failures (spec §11.7 explicit prohibition).
- Cross-eval orchestration (running Spec A + B + C from one entry point).

---

## 12. Sequencing summary

```
Phase 1 (MVP loop, 1 day)
  ├─ backend/app/auth/middleware.py: eval bypass
  ├─ backend/tests/evals/chat/: full directory
  ├─ Migrate 10 legacy rows
  └─ 1 portfolio attribution scenario + portfolio_attribution_v1 rubric live
  (NB: /eval/health already shipped with Spec A — reused, not added)
        │
        ▼
Phase 2.2 (Mocks, ½ day — smaller than originally planned)
  ├─ backend/app/eval/: mocks (install_mocks at lifespan), context (per-request override)
  ├─ /eval/context POST/DELETE endpoint inline in main.py
  └─ Self-tests for gate, mocks, seed determinism
        │
        ▼
Phase 2.1 (Remaining rubrics + scenarios, 2 days)
  ├─ 3 rubric bodies in rubrics.yaml
  ├─ Spot-check transcripts (3 good + 3 bad per rubric)
  ├─ 25 scenario JSONL bodies
  └─ Seed factories for each scenario kind
        │
        ▼
Phase 2.3 (Inter-judge agreement, ½ day)
  ├─ agreement.py with inline Spearman
  ├─ --check-agreement CLI flag
  └─ Per-rubric ρ in report header
        │
        ▼
Phase 2.4 (Per-PR CI, ½ day)
  ├─ scripts/eval-chat-pr.sh
  ├─ .github/workflows/eval-chat-pr.yml
  ├─ Diff → tags inference
  └─ PR comment formatter
```

Total: ~4½ working days end-to-end (Phase 2.2 collapses because Spec A pre-shipped
`/eval/health` and the `EVAL_MOCKS` env gate).

---

## 13. Acceptance criteria

This design is "delivered" when:

1. All five phases have landed implementation plans (each via `writing-plans`).
2. Each plan's phase passes its own self-tests + a clean run of the corresponding scenario
   subset.
3. A full pre-release run (`python -m backend.tests.evals.chat.run_eval --max-cost-cents 500`)
   completes with a tagged report and zero forbidden-signal hits.
4. Inter-judge agreement on each rubric ≥ 0.8.
5. The PR-time workflow has been exercised on at least one PR with each tag-inference path.
