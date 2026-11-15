# Offline Advisor Improvement

Status: implementation approved; offline fixture workflow implemented. Paid validation
has not been run. See `backend/tests/evals/chat/OFFLINE.md` for executable commands
and current scope limits, including production memory integration and judge calibration.

## Intent and boundaries

Improve the advisor through reproducible offline experiments on scripted short
conversations, not through automatic changes to live chat. Ordinary deterministic
features use normal tests plus Playwright verification of actual UI interactions;
they do not need an optimizer workflow.

The user approved implementing and testing updates to memory, response instructions,
effort settings, and numerical tools in an isolated environment, subject to a fixed
budget and attempt limit. Production promotion still requires human approval.

## Approach

Extend the existing chat-evaluation harness rather than build another agent system.
Manual-only report review would be simpler but would not provide the requested
candidate loop. Unrestricted self-modifying code would make attribution and safety
harder. Use Codex as a bounded operator that applies versioned configuration changes and
sandboxed numerical-tool patches, with tests before execution.

```text
Synthetic fixtures + scripted conversations + frozen baseline
    -> isolated runner -> every answer, tool trace, memory events, usage
    -> deterministic checks + blinded Gemini 2.5 Flash judge
    -> round 1 -> update 1 -> round 2 -> update 2 -> round 3
    -> report trajectory -> carry validated setup to next conversation
    -> final setup + full development-set regression evaluation
    -> freeze selected candidate -> sealed holdout evaluation
    -> comparison report -> human promotion decision
```

"Offline" means outside the live user path; real model calls still require network
access and incur costs. The evaluated advisor model must match the model intended
for the chatbox when promoted; this design does not switch the live app yet.

## Selected roles

| Role | Selection | Responsibility |
| --- | --- | --- |
| Advisor | `deepseek/deepseek-v3.2` via OpenRouter | Answer scripted conversations with financial tools |
| Judge | `google/gemini-2.5-flash` via OpenRouter | Grade directness, concision, and interpretation against evidence |
| Optimizer | Codex in the active development task | Inspect development failures, apply changes, run tests, and resume evaluations |

Flash is an economical judge, not assumed stronger than the advisor. Calibrate its
rubric against human-rated examples. Deterministic checks validate numerical claims;
instrumentation measures cost, latency, and tool calls. The judge does not invent
reference values or estimate measured resource use. Blind it to candidate identity.

The first version has no autonomous optimizer API or daemon. Codex operates the
three-round loop while this task is active, using runner commands and persisted
checkpoints. Save scenario order/index, round number, setup hashes, update decisions,
remaining API budget, and completed-call IDs for safe resumption without repeating
completed paid calls. Unknown call outcomes require reconciliation before retry.
An unattended optimizer runtime is explicitly out of scope.

Record the actual provider and model identifier returned for each API call. Do not
silently switch model families during comparisons. Codex's development workspace
must not expose held-out case contents to its optimizer context; final evaluation
uses a separately controlled holdout store. Cases already inspected by Codex belong
to development, not to a claimed unseen test set.

## Scenarios and memory

Each scenario has 3-5 scripted user turns, fixed financial fixtures, independently
checked expected evidence, per-turn assertions, and frozen resource budgets.
Capture and evaluate every answer, not only the last reply. Preserve history inside
a conversation; reset financial data, sessions, and user-memory fixtures before each
round. Carry versioned learned setup changes, not residual user/session state.

Memory-policy scenarios have an acquisition conversation, an explicit awaited memory
update, and a fresh-session probe. The probe must succeed through persistent memory,
not residual session history. Baseline and candidate start with identical memory and
receive identical acquisition inputs. Record insert/update/merge/delete/reject events.
Test correction, expiry, unsupported facts, malicious content, and tenant boundaries.

Split acquisition examples and scenarios into development and sealed holdout sets,
grouped to avoid near-duplicate leakage. The optimizer sees development results only.
On holdout, the frozen memory policy may learn from that scenario's designated
acquisition turns, but never from probe answers, reference answers, or judge feedback.
No user/session state carries between scenarios. Development setup changes do carry
forward in the declared scenario order, which must be recorded for reproducibility.
Reusable learned examples are versioned development artifacts, never copies of
fixture answers presented as financial facts. Reusing inspected holdout failures for tuning
requires retiring those cases to development and obtaining fresh holdout cases.

## Six metrics

Normalize every component to [0, 1] before aggregation; higher is better. Rubric
scores on a 0-100 scale are divided by 100. Validate raw ranges before conversion;
missing, non-finite, or out-of-range judge values invalidate the result rather than
being silently clamped. Store raw values and the normalization version in reports.

| Metric | Weight | Evidence |
| --- | ---: | --- |
| Numerical accuracy | 10 | Reference values, units, periods, scope, formulas, claim support and required-answer coverage |
| Directness | 8 | Answers the actual question first, covers required parts, respects follow-ups |
| Concision | 2 | No repetition or irrelevant detail; length expectations depend on task |
| Cost efficiency | 2 | Advisor, retrieval-related model calls, retries, and memory-update usage |
| Latency efficiency | 2 | Complete answer latency, including tools/retries; memory-update latency reported separately |
| Tool efficiency | 2 | Calls above a scenario's justified allowance; redundant calls diagnosed explicitly |

Overall = (10A + 8D + 2C + 2Cost + 2Latency + 2Tools) / 26.

Overall is in [0, 1]. Multiply by 100 only for optional percentage display.

Proposed normalization for each resource x uses a frozen target t and upper bound u:
1 when x <= t; (u-x)/(u-t) when t < x < u; 0 when x >= u.
Require u > t >= 0. Count all tool attempts, including retries, and report raw totals.
Necessary calls are included in the justified allowance; skipped required evidence
fails correctness regardless of resource savings. Judge API costs are excluded from
answer-quality scoring but included in the API experiment spend cap. Codex optimizer
usage is separate account usage, not an OpenRouter charge; record it when available
and otherwise label it unmeasured, never zero. The API cap does not cap Codex usage.

Compute quality scores per answer, then equal-weight means across turns in a
conversation. Compute resource scores at conversation level against its budgets.
Aggregate conversations equally, showing per-turn failures and all six components.
Missing telemetry makes the result incomplete, not perfectly efficient. Questions
requiring no numbers are scored for correct evidence/abstention; omission of required
numbers is a failure, not a way to obtain full accuracy.

Material numeric errors, fabricated evidence, unauthorized actions, and cross-user
memory leakage fail independently of the weighted average. A proposed gate is >=0.95
overall with no critical failures and no regression in accuracy or directness.
Calibrate judge scores against human-labeled development answers before treating 0.95
as a release threshold. Judge extracts/interprets claims; deterministic comparisons
validate supported claims with predefined rounding tolerances. Ambiguous claims go
to review rather than silently passing. Independently assert fixture math to avoid
certifying a broken engine against itself.

## Allowed experiments

- Memory: extraction/update prompt, merge/correction/expiry policy, retrieval settings.
- Response: answer structure, clarification policy, length guidance.
- Effort: reasoning settings where supported, evidence verification and tool budgets.
- Tools: implement missing deterministic numerical functions or parameter contracts
  inside a disposable isolated workspace, run independent expected-value and security
  tests, and register only validated candidates in the eval tool registry.

Tool changes cannot access real credentials, production databases, arbitrary networks,
or unrestricted shell execution. The optimizer cannot grant permissions or modify its
own runner, test oracle, or sandbox. Failed patch validation consumes an update slot;
retain the last executable setup and report the rejected patch. Work requiring new
permissions, production writes, or schema changes is reported as blocked, not applied.

Prefer one track per update for attribution; record all changed tracks when a coupled
fix is necessary. Cross-track gains are overall-system gains, not proof of memory-only
learning. Memory-learning
claims require a memory-only comparison with model, response prompt, tools, and other
settings fixed. Memory-only ablations distinguish policy gains from general prompt
improvements. Treat combined changes as a later integration experiment.

Optimizer output must conform to an allowlisted schema. It cannot change scoring,
weights, reference evidence, holdout access, tenant controls, budget enforcement, or
production settings. Treat candidate text and conversation content as untrusted data.
Use pinned versions and archive baseline/candidate manifests and content hashes.

## Limits, gates, and reports

### Sequential three-round loop

The unit is one scripted conversation, including all its follow-ups (and acquisition
phase for memory cases). Replay the same complete conversation and fixtures in every
round; do not tune on a follow-up in isolation and lose its preceding context.

1. Round 1: evaluate the incoming setup and diagnose failures.
2. Apply update 1, test it, reset fixtures, and replay in round 2.
3. Apply update 2, test it, reset fixtures, and replay in round 3.
4. Output the three-round trajectory and final validated setup; move to the next
   conversation in the fixed development set with that setup.

There are exactly three evaluation rounds and at most two updates per conversation,
not an initial attempt plus three retries. If the target is already met or there is
no justified change, record a no-op update and use the remaining rounds to check
repeatability. These sequential rounds are not independent statistical replicates.
If a change fails hard gates or previously passed deterministic regressions, roll it
back and retain the last admissible setup. Ordinary score regressions remain visible;
the report flags them rather than claiming monotonic improvement. Budget/infrastructure
stops produce a partial report, with unexecuted rounds marked explicitly.

After the last conversation, output the cumulative memory/response/effort/tool setup
and replay the entire development set without further tuning to expose forgetting
or regressions. Compare it with the frozen initial baseline. A separate frozen paired
evaluation may repeat runs for uncertainty; it does not create more optimizer rounds.

A paid invocation has a user-approved ceiling of USD 1.00 per scripted conversation,
shared by all follow-ups, three rounds, two updates, and advisor/judge/memory API
calls including retries. Restarting a run must not reset this allowance. Codex usage
is separate. Additional regression/holdout calls must use the same remaining
conversation allowance or obtain a separate explicit budget; never mint a new
allowance silently when tuning ends. Reserve conservative cost
before every advisor/judge/memory API call, enforce output bounds, and reconcile usage.
Unknown pricing or unbounded cost fails preflight. Stop on budget exhaustion, repeated
infrastructure errors, or completion; never lower thresholds to force success.

Select a candidate using development results only; run the sealed holdout once for
that frozen selection. Report paired differences and conversation-level uncertainty,
not repeats treated as independent samples. A small pilot is not proof of generalization.
Holdout failure produces a report, not an automatic retry against the same test set.

Report code SHA and dirty-diff hash, fixture/dataset/split/rubric versions, model and
provider identifiers, prompt/memory/tool/config hashes, every component score, hard
failures, raw calls, p50/p95 latency, usage and estimated/reported spend, missing data,
and candidate rationale. For every update, include the triggering scenario/turn IDs,
failed answer excerpt, expected versus observed evidence, six before/after scores,
diagnosis, exact config/code diff, validation results, and retained/reverted decision.
Distinguish suspected causes from causes supported by controlled comparisons. Explain
unresolved failures after round 3 and show the setup inherited by the next scenario.
Export the final setup manifest with prompt files, memory policies/examples, effort
settings, tool patches/tests, version hashes, and rollback reference, not just a score.
Report memory-update latency separately. Reports use synthetic
data and exclude credentials. Production promotion is manual and retains a rollback
version; user deletion and access restrictions apply to retained memory versions.

## Integration and verification

Current runner gaps: only the last answer is graded; seeding happens before repeated
runs rather than before each run; the cost flag is advisory; failure reports return
exit code 0. Fix these foundations before enabling the optimizer. Also fail closed
on missing traces, require dedicated allowlisted eval storage, and prohibit production
credentials. Eval authentication shortcuts must never enable a production bypass.

Implementation boundaries: scenario schema, isolated runner, evidence/telemetry,
scorer, candidate validator, checkpoint store, and report writer within the existing
harness. Codex supplies candidate edits externally; no optimizer-model client is needed.
Mock provider responses to test scores, hard gates, spend reservation, state reset,
holdout isolation, malformed candidates, missing usage, retries, and CLI exit status.
Test fresh-session memory retention and rejection/correction with synthetic fixtures.
Use Playwright for send/follow-up/stream/render/error UI journeys, separately from
model quality. Add tests for normalization boundaries, exactly three rounds/two update
slots, rejected patches, no-op updates, state reset versus setup carry-forward, full-set
regression replay, and complete trajectory exports. This document does not itself run
paid calls, change the live app, deploy generated tools, or migrate providers.
