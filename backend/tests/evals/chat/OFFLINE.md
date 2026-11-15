# Offline advisor workflow

## Whole-set retest (v2)

`offline_campaign` runs a complete question set in each round, with at most three
rounds and two operator updates. It stops early when every conversation passes.
It carries settled costs from a previous ledger into an immutable **USD 1 total
campaign cap**, shared by all advisor, judge and memory requests. Pending costs
must be reconciled before migration. The previous ledger remains unchanged; its
hash and cumulative cost are checked on resume. This is an explicitly authorized
new scorer version, never an automatic reset of an exhausted allowance.

```sh
../.venv/bin/python -m tests.evals.chat.offline_campaign init --run-dir tests/evals/chat/reports/offline-retest --dataset private-dataset.json --setup tests/evals/chat/offline-setup-v2.json --prior-ledger prior-run/ledger.sqlite
../.venv/bin/python -m tests.evals.chat.offline_campaign run-round --run-dir tests/evals/chat/reports/offline-retest --env-file .env
../.venv/bin/python -m tests.evals.chat.offline_campaign update --run-dir tests/evals/chat/reports/offline-retest --candidate candidate.json --reason "Observed failure and proposed remedy" --cases scenario_id/1
```

Use only Git-ignored local paths for real financial fixtures. `spans-v2` scenarios
use deterministic numeric spans, with the judge mapping span IDs to frozen metric
keys. Formatting is not an oracle. Explicit approximation has a precision-aware
tolerance; exact claims retain cent-level checks. Repeated figures, written counts,
signed decreases, dates and numbered lists have regression coverage. Unsupported
numeric or semantic claims are hard failures. Incomplete judge mappings are
separate `evaluator_errors`, preserving independently valid directness/concision
scores but preventing promotion. Paragraph/answer length also limits concision.

Each turn supplies `checks: {rule_id: description}` for evidence scope, refunds,
unsupported inference, absent data, transfers and persistence. These checks and
metric mappings are still model judgments: authored rubric anchors are **not human
calibration**, and inspected questions are **not holdout**. No automatic live-app
promotion occurs. `retained-setup.json` and `last-tested-setup.json` distinguish a
whole-set passing candidate from a merely attempted change.

`financial_evidence.py` provides pure, tested holdings concentration, outside-cash
accounting, complete owned transfer-pair totals, explicit refund-verification
handling and exact-boundary wealth coverage. Missing basis, ownership or snapshots
remain unavailable; they are never replaced by invented values. These are offline
evidence helpers, not a deployment of new live advisor tools.

The original per-conversation runner below remains available for synthetic tests
and historical artifacts. Its scores are not directly comparable with v2 scores.

DeepSeek V3.2 answers scripted conversations; Gemini 2.5 Flash judges; Codex operates
the improvement loop. This isolated fixture adapter does not connect to Supabase or
change the live `/advisor/chat` route. Its results are not evidence that the live
Gemini chatbox or production memory subsystem has improved.

## Initialize without spending

From `backend/`:

```sh
../.venv/bin/python -m tests.evals.chat.offline_workflow init --dataset tests/evals/chat/offline-development.json --setup tests/evals/chat/offline-setup.json --run-dir tests/evals/chat/reports/offline-pilot
../.venv/bin/python -m tests.evals.chat.offline_workflow report --run-dir tests/evals/chat/reports/offline-pilot
```

Neither command makes API calls. Run directories are ignored by Git. The shipped
synthetic examples are development data, not an unseen benchmark. Never put API keys
or personal records in a setup, fixture, or report.

## Three rounds, two updates

Put a fresh `OPENROUTER_API_KEY` in the process environment, not command arguments
or candidate JSON. Rotate keys previously pasted into chat. This command makes
paid calls and runs one complete 3-5-turn conversation:

```sh
../.venv/bin/python -m tests.evals.chat.offline_workflow step --run-dir tests/evals/chat/reports/offline-pilot
```

Alternatively, from `backend/`, append `--env-file .env`. Only
`OPENROUTER_API_KEY` is read from that file; it is never included in manifests.

Codex reviews the reports, edits a candidate setup, then applies it with provenance:

```sh
../.venv/bin/python -m tests.evals.chat.offline_workflow update --run-dir tests/evals/chat/reports/offline-pilot --candidate candidate.json --reason "Answer buried under repeated advice" --cases spending/1 spending/2
../.venv/bin/python -m tests.evals.chat.offline_workflow step --run-dir tests/evals/chat/reports/offline-pilot
```

Repeat update/step once more: baseline round 1, update 1/round 2, update 2/round 3.
The next step advances to the next conversation with the retained setup. No additional
approval is needed for isolated updates. Identical candidates record explicit no-ops.
Rejected patches consume a slot. Hard-failing rounds roll back atomically; unverified
interrupted candidates do not carry forward. Financial/session state resets each round.

Codex runs these commands while the task is active. There is no autonomous optimizer
API. Checkpoints make the workflow resumable without resending completed paid calls.

## Allowed changes

Setup accepts only `response_prompt`, `memory_prompt`, `memory_policy`, `effort`, and
`tools`. Models, weights, reference answers, scoring, and budgets cannot be changed
by a candidate. DeepSeek reasoning supports an on/off switch: low/medium/high all
enable it, not distinct reasoning strengths. Judge generation settings remain fixed.

Memory currently covers explicitly quoted style/detail/language preferences,
correction, deletion, and capacity. Acquisition happens before a fresh-session probe;
acquisition history is not passed to the advisor. Production vector retrieval,
time-based expiry, and the Supabase notes schema are not exercised by this adapter.

Tools use bounded arithmetic expressions, not arbitrary Python. An example tool:

```json
{
  "name": "cash_coverage",
  "description": "Months of cash assuming no income",
  "expression": "cash / monthly_expenses",
  "tests": [{"metrics": {"cash": 12000, "monthly_expenses": 3000}, "expected": 4}]
}
```

Add it to the setup's `tools` list. Imports, calls, attributes, indexing, exponentiation,
files, network, and external mutations are unavailable. Accepted tests accumulate in
an immutable registry, surviving deletion/replacement of tools. New test oracles need
independent review; self-written tests alone do not prove a new formula correct.
Broader generated tool code needs a separately designed sandbox.

## Scores and hard stops

Normalize all components to [0,1], then compute:
`(10*accuracy + 8*directness + 2*concision + 2*cost + 2*latency + 2*tools) / 26`.
The provisional target is 0.95. Material numeric/safety failures override the mean.
The judge still needs calibration against human-rated development answers.

Claim extraction uses exact answer quotes; code compares values against frozen
expectations. Missing claims fail. Uncovered digit spans require review, sometimes
conservatively flagging dates/list numbering. Semantic interpretation remains partly
judge-dependent: this is not a guarantee of detecting every numerical error.
Each turn can also supply a frozen `references` map for optional, verified numbers.
Those numbers need not appear, but are checked when claimed. Required `expected`
values take precedence and cannot be overridden by optional references.

Cost efficiency includes advisor and memory calls, not judging. Answer latency
includes advisor/tools, not offline memory extraction or judging; all are separately
reported. Every API role shares **USD 1.00 per conversation**, including three rounds,
retries, and frozen replays. Codex account usage is separate and unmeasured, not zero.

Code reserves conservative cost before dispatch, bounds tokens, and requests provider
price ceilings. No automatic HTTP retries/redirects. Budget denial persists a terminal
stop across restarts; prompts or cheaper retries cannot clear it. Provider adherence
to token/price constraints is an external assumption: unexpected charges are recorded
and stop further calls, never hidden.

## Resume and reconciliation

Reuse the same directory. Request hashes prevent incorrect cache reuse; changing
harness source invalidates the run to avoid mixing scorer versions. Candidate setup
edits still work. Never create another run to bypass an exhausted budget.

Unknown outcomes retain reservations. Verify an original provider receipt before
reconciling locally, without another API request:

```sh
../.venv/bin/python -m tests.evals.chat.offline_workflow reconcile --run-dir tests/evals/chat/reports/offline-pilot --call-id spending/round-1:0 --receipt verified-provider-receipt.json --latency-seconds 2.3
```

Never invent a receipt ID, cost, or latency. Missing verified latency settles known
spend but stops scoring. Receipts cannot be reused. Unresolvable outcomes can be
stopped explicitly without releasing their reservations:

```sh
../.venv/bin/python -m tests.evals.chat.offline_workflow stop --run-dir tests/evals/chat/reports/offline-pilot --question spending --reason "Provider outcome could not be verified"
```

## Frozen comparison

After development, each command evaluates one frozen baseline/final arm; repeat until
`replay_complete`. It uses the remaining dollar allowance, never a fresh tuning budget:

```sh
../.venv/bin/python -m tests.evals.chat.offline_workflow replay --run-dir tests/evals/chat/reports/offline-pilot
```

For holdout, a separate operator initializes a run from a controlled dataset marked
`split: holdout`, the original baseline, and `--candidate final-setup.json`. Use
`replay`; updates are refused. Dataset custody/permissions are operator responsibilities.
Do not expose holdout questions or traces to the optimizer while tuning. Inspected
cases must be retired to development before reuse for learning.

Reports show paired deltas and a conversation-level bootstrap interval when at least
two pairs exist. One pair per scenario is only a pilot; repeated studies need explicit
budget planning. Production promotion is always manual, after calibration and review.

## Reports and checks

`report.md`, `report.json`, and `final-setup.json` preserve scores, answers, raw judgments,
tool traces, memory events, change reasons/diffs, triggering cases, rollbacks, usage,
model/provider metadata, code hashes, and unresolved failures. SQLite is authoritative.

Exit codes: 0 success; 1 rejected update/error/failed complete comparison; 2 hard stop
or incomplete comparison; 3 awaiting a Codex update. `report` is informational and
returns 0 for a successful export even when results contain failures. The old
`run_eval` live command remains disabled to prevent bypassing the guarded transport.

```sh
../.venv/bin/python -m pytest tests/evals/chat tests/evals/backend tests/portfolio -q
```

The transport, executor, and three-round lifecycle are tested together with mocked
OpenRouter HTTP. `frontend/e2e/chat-workflow.spec.ts` checks mounted UI send/follow-up,
rendering, errors, and fragmented SSE with synthetic auth and no paid calls. Those
tests do not establish live model quality.
# Evidence-first v3

The production implementation in `app/advisor/evidence` is also the v3 offline execution path. Gemini 2.5 Flash plans read-only metrics; DeepSeek V3.2 writes metric-referenced narrative, which code validates and renders. Definitions and ranking arithmetic are code-owned.

Run the versioned CLI with `python -m tests.evals.chat.offline_campaign_v3`; use `init`, `run-round`, `update`, or `report`. Initialization requires an explicit development dataset, setup, prior ledger and new run directory. The prior ledger remains immutable and its spending is carried into the cumulative $1 ceiling. Unknown provider charges stop execution. The three-round/two-update limit is enforced in code.

V3 evaluator errors are unscorable, not zero-accuracy answers. Unscorable conversations cannot pass. Necessary tool requests are not penalized; redundant identical requests within a turn are deduplicated and scored as `max(0, (3 - redundant_requests) / 3)`. Keep raw call counts and cost/latency alongside scores.

`compare_campaigns.py` re-scores cached baseline tool efficiency and evaluator validity without paid rejudging. Numerical extraction and semantic judge prompts differ between versions, so adjusted aggregate differences are not a controlled model-only comparison. Always disclose valid-score coverage and retain original scores.

Live UI activation requires applying `20261011_transfer_counterparty_evidence.sql` and `20261011_advisor_pending_analysis.sql` in Supabase, then setting `EVIDENCE_ADVISOR_ENABLED=true` in backend environment configuration. The feature defaults off. Financial analysis and existing Goals and actions remain separate modes. Pending analysis state is not long-term preference memory.

The aggregate is `100 * (10*A + 8*D + 2*C + 2*Cost + 2*Latency + 2*Tools) / 26`, with every component in `[0, 1]`. Passing requires at least 95 and no hard failures. Accuracy includes completeness of required metric references, not just correctness of the numbers that happen to appear. Cost and latency use the scenario's frozen efficiency budgets. Judge calls count toward the hard dollar cap, but not the advisor's operational efficiency score.

Candidate application changes between settled rounds require `upgrade_runtime` with an archived, hash-verified copy of the previous runtime and an explicit reason. This is allowed only after rounds one and two. Scoring, accounting, transport, original receipts and question fixtures cannot change. Record source transitions alongside prompt updates; this is not a prompt-only experiment. The last tested setup is not automatically the retained setup.

The executor supplies summary metrics as a dependency even when the planner selects only contributors. Non-contributor tools include both comparison periods and need only one request. Frozen fixtures without a year do not offer month selection; live adapters can select a completed month. These constraints avoid asking the model to reconstruct arithmetic or infer a missing year.
