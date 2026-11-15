# Evidence-first advisor

Status: design for review; not implemented or promoted.

## Intent

Answer financial questions with deterministic calculations, stable definitions, explicit missing-data boundaries, and resumable conversations. Reduce numerical, ranking and unsupported-inference failures observed in offline evaluation. No claim of generalization is made from repeated development questions.

## Model Responsibilities

1. Gemini 2.5 Flash produces a structured evidence plan from the question, relevant conversation state, authorized account scope and tool catalog. It selects tools, periods, grouping, ranking measure and result limit. It does not calculate financial answers or invent metric definitions.
2. The backend validates and executes the read-only plan. DeepSeek V3.2 receives the resulting evidence package and writes the narrative. Neither model determines account authorization.

Use separately configurable planner and writer model IDs through the existing provider transport. Do not silently substitute models. Provider failures produce a retryable error without implying that data is missing. Call counts, token usage, latency and costs are recorded by stage; retries must respect the active budget and retry policy.

The normal path has two model calls with deterministic tool execution between them. An invalid plan stops with a recoverable error; insufficient or ambiguous scope prompts clarification rather than unbounded replanning. Mutating tools are excluded from this analytical path.

## Stable Metric Contracts

Each analytical tool has a versioned, code-owned output schema and metric definitions shared by the planner catalog, execution result, writer and evaluator. Definitions are never generated or paraphrased into authoritative metadata by a model.

Each definition specifies metric ID, plain-language meaning, unit, sign convention, formula, aggregation grain, inclusion/exclusion rules, time boundaries, rounding, null meaning and limitations. Changes require a version change and contract tests. Dynamic values, account scope, coverage, source references and data version are separate from static definitions.

The backend constructs the evidence package from validated tool results and the matching registry version. Unknown IDs or version mismatches fail validation. Imported descriptions remain untrusted data, not instructions. Only necessary aggregated financial evidence is sent to models; account identifiers are scoped and aliases used where appropriate.

## Deterministic Contributors

A contributor tool supports merchant, category, income-source and holding groupings, with explicit supported measures such as current value, signed change and absolute change. It aggregates first, calculates with decimal arithmetic, sorts deterministically, then returns top N.

Results include rank, current value, comparable previous value, delta, total, omitted remainder, population count, tie handling and coverage. A percentage is unavailable when its denominator is zero or unsuitable; it is not invented. Ranking by amount is distinct from ranking by change. Merchant normalization limitations remain visible.

The writer receives the selected ranked results and their context, not raw transaction history. It must not recompute rankings. Tests cover ties, refunds, negative changes, zero baselines, account overlap and incomplete periods.

## Transfer Evidence

An automatic internal match requires equal opposite amounts, matching currency, a compatible date window, different owned accounts, reciprocal resolved account/counterparty identities and an unambiguous one-to-one pairing. Match using stable resolved identities, not similar names alone. Preserve explicit user decisions and store evidence provenance.

The two ledger rows represent one transfer: X's outgoing counterparty resolves to Y, while Y's incoming counterparty resolves to X. Missing identity, multiple candidates, currency conversion or fee discrepancies remain reviewable rather than force-matched. Existing automatic matches must not be treated as newly verified reciprocal matches without supporting evidence.

An internal transfer does not establish rebalancing, funding source or intent. Investment in/out totals alone cannot establish ownership. Zero confirmed external transfers is not proof that no external transfers occurred while unresolved records remain.

## Narrative And Validation

The writer returns structured narrative blocks referencing approved metric IDs. The backend renders financial numbers using tool values and formatting rules, rejecting unknown references and ungrounded financial numeric literals. Ranked lists render from ranked result IDs. Validation occurs before displaying a completed answer; do not stream unvalidated financial claims as final text.

Definitions, scope and availability flags accompany evidence. Semantic checks remain necessary: valid numbers do not prevent unsupported causal, lifestyle, persistence or ownership claims. The writer must distinguish observation, inference and unavailable evidence. Failed validation returns a clear recoverable failure, not a fabricated substitute answer.

## Missing Data And Resume

Return available answers together with a structured missing-evidence requirement when possible. Distinguish unavailable history from provider errors, missing permissions and incomplete imports. Navigation targets are mapped by the UI to actual routes/import actions, never invented by the model.

Persist session ID, pending question, period, required evidence, status and data version in conversation workflow state. Reuse existing owned chat sessions/messages and restore the selected or most recent session on reopening. This is not long-term preference memory.

Offer an upload action naming the missing evidence. After a successfully committed import, recheck coverage and show an explicit **Continue analysis** button when relevant. Previewing or canceling an import does not trigger continuation. A partial import reports what is still missing. Resume re-executes the evidence plan against current data in the same conversation; it does not reuse stale financial values or launch a paid call automatically.

Enforce session ownership on every read/resume and make duplicate continuation requests idempotent. Lasting preferences may be stored in memory separately; transient missing-data statements and computed balances are not durable user facts.

## Verification And Rollout

Unit and contract tests cover static definitions, ranking, reciprocal matches, ambiguity, missing coverage, plan validation and number rendering. Integration tests cover planner/tool/writer contracts and stage failures. Playwright verifies session restoration, upload/cancel/partial-import flows and explicit continuation without duplicate answers.

Offline evaluation scores planner tool selection and scope separately from writer fidelity, then evaluates the final answer using the existing normalized six-metric rubric. Retain numerical and semantic hard gates. Calibrate judge/reference coverage before interpreting scores as quality estimates, and use an unseen holdout before claiming improvement.

Keep this architecture behind an explicit rollout boundary until validated. The completed prior three-round campaign is closed; do not reset its ledger or spend its remaining allowance implicitly. A further paid evaluation requires a newly authorized campaign and explicit cumulative budget treatment.

## Sequence

1. Metric registry, deterministic contributors and reciprocal-transfer evidence.
2. Planner/executor/writer orchestration and validated rendering.
3. Persisted pending questions, session restoration and upload/resume UI.
4. Deterministic and browser verification, followed by an authorized offline comparison.
