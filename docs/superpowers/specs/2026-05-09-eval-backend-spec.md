# Spec B — Backend Correctness Eval

> **Layer:** B of three (`A = frontend behavior`, `B = backend correctness`, `C = chat-advisor quality`).
> **Cross-references:** Spec A (`2026-05-09-eval-frontend-spec.md`) owns UI rendering; Spec C
> (`2026-05-09-eval-chat-quality-spec.md`) owns LLM judgment + narration quality. This spec
> owns everything between the DB and the HTTP/MCP boundary — no LLM, no browser.

---

## 1. Purpose + Scope

Spec B verifies that every **MCP tool**, **REST endpoint**, and **engine module** in Suan-Pan
produces the correct output given known fixture input. "Correct" is defined by:

1. **Golden snapshots** — hand-computed JSON stored in `backend/tests/evals/backend/golden/`.
2. **Mathematical invariants** — identities that must hold for any valid input.
3. **Schema round-trips** — every API response passes through its Pydantic model without
   dropping or adding fields.
4. **Differential consistency** — where an MCP tool and a REST endpoint are supposed to agree,
   they do, given identical input.

**No LLM in any test in this spec.** Statement-parser tests mock Gemini with a canned JSON
string (same pattern as the existing `test_statement_parser.py`). All other tests are
purely deterministic.

**What this spec does NOT cover:**

- Whether the LLM advisor narrates engine output correctly (Spec C).
- UI rendering, DOM presence, or network call shapes (Spec A).
- Live external services (Plaid sandbox, FRED live, yfinance live) — all mocked here; live
  integration is validated by Plan 2 / Plan 3 / Plan 4 smoke tests.

---

## 2. Methodology

- **pytest** (existing suite) + golden snapshots + `hypothesis` property-based invariants.
  `hypothesis>=6.100` is **not in `requirements.txt`** — must be added before invariant tests run.
- **Differential tests** call the MCP tool function and the REST handler function with an
  identical MagicMock DB and assert field-by-field equality.
- **Schema round-trips**: `SomeSchema.model_validate(raw_dict)` must succeed after every call.
- **No LLM**: engine tests need no mocking. `statement_parser.py` tests mock Gemini via
  `patch("app.portfolio.statement_parser.genai.Client", return_value=fake_client)` — the
  existing `test_statement_parser.py` already demonstrates this pattern correctly.

**Floating-point tolerances (strict per category):**

| Category | Tolerance | Example |
|---|---|---|
| Integer arithmetic / exact money | `1e-9` | attribution bucket sums |
| Decimal money math (division, percent) | `1e-6` relative | exposure percent, reval totals |
| Percentage / bps fields | `0.5 pp` absolute | `ten_year_yield_change_bps` |
| Monte Carlo percentile outputs | exact equality across N=5 same-seed runs | `p50 == p50` |

Apply via `pytest.approx(rel=1e-6)` or `pytest.approx(abs=0.005)`.

---

## 3. Working with Seed

```python
from backend.tests.evals.shared.seed import Seed

fixture = (
    Seed()
    .with_user(user_id="u-test")
    .with_account(name="Test Brokerage", type="brokerage", balance=14200.0)
    .with_security(ticker="NVDA", asset_class="equity", sector="Technology", region="US")
    .with_snapshot(
        account_id="acc-test-brokerage",
        snapshot_date="2026-04-01",
        holdings=[{"ticker": "NVDA", "quantity": 10, "price": 820.0}],
    )
)
applied = fixture.apply(db)
# applied.user_id, applied.account_ids, applied.snapshot_ids are stable across runs
```

Call `apply()` once per test in a `"function"`-scoped pytest fixture.

### Known limitations for live DB tests

**Limitation 1 — `snapshot_holdings` insert is not idempotent against a live DB.**
`Seed.apply()` inserts holding rows each time it is called because `snapshot_holdings` has no
unique constraint that `upsert(on_conflict=...)` can exploit (the primary key is a
DB-generated UUID). If your test calls `apply()` twice against a real Supabase client, you
will accumulate duplicate holding rows and corrupt the snapshot. Workaround: scope the pytest
fixture to `"function"` and ensure the database is cleaned between test runs, or add a
delete-then-insert pattern in `conftest.py`:
```python
db.table("snapshot_holdings").delete().eq("snapshot_id", snap_id).execute()
```
before calling `fixture.apply(db)`. Mock-safe tests (using `MagicMock`) are unaffected.

**Limitation 2 — `investment_transactions` upsert uses DB-generated id.**
The `investment_transactions` table has no unique constraint on `(account_id, date, type,
ticker, amount)`. As a result, `Seed.apply()` calls `upsert(on_conflict="id")` against a
generated UUID that is fresh each call, which effectively inserts a new row every time against
a live Supabase client. For idempotent live-DB txn seeding, either: (a) pre-generate
explicit `id` values and pass them in the seed payload, or (b) delete existing rows for the
account before seeding. This is a known gap; a migration adding the composite unique
constraint would fix it permanently.

---

## 4. Function / Endpoint Inventory

### 4a. Engine Modules

One test file per row: `backend/tests/evals/backend/test_engines_<module>.py`.

| Module path | Function | Input fixture id | Golden snapshot file | Invariants checked |
|---|---|---|---|---|
| `app/engine/snapshot.py` | `compute_snapshot(accounts)` | `single-account-2-holdings` | `golden/engine_snapshot_basic.json` | Snapshot total consistency (§6) |
| `app/engine/feasibility.py` | `score_goal_feasibility(target_amount, current_progress, monthly_surplus, target_date)` | `feasibility-basic` | `golden/engine_feasibility_basic.json` | Score ∈ [0,100]; months_to_goal > 0 when progress < target |
| `app/engine/simulation.py` | `simulate_decision(decision, accounts, goals, monthly_income, monthly_expenses, liquid_override)` | `simulation-car-purchase` | `golden/engine_simulation_car_purchase.json` | All goal scores change by ≤ 100 pp; scores remain ∈ [0,100] |
| `app/engine/monte_carlo.py` | `run_monte_carlo(initial_portfolio, monthly_contribution, years, ...)` | `monte-carlo-30yr` | `golden/engine_monte_carlo_30yr.json` | Monte Carlo determinism (§6): N=5 runs with seed=129 → identical |
| `app/engine/cashflow.py` | `project_cashflow(liquid_assets, monthly_income, monthly_expenses, months, ...)` | `cashflow-12mo-rsu` | `golden/engine_cashflow_12mo_rsu.json` | Each month's `balance` monotonically computable from prior; no NaN |
| `app/portfolio/attribution.py` | `compute_attribution(start_value, end_value, transactions)` | `attribution-mixed-txns` | `golden/engine_attribution_mixed.json` | Attribution identity (§6) |
| `app/portfolio/exposure.py` | `compute_exposure(holdings, references, dimension)` | `etf-with-look-through` | `golden/engine_exposure_etf.json` | Exposure percentages sum to 100% (§6); Look-through residual non-negative (§6) |
| `app/portfolio/reval.py` | `revalue_at(holdings, as_of, prices, cash)` | `single-holding` | `golden/engine_reval_single.json` | Reval correctness (§6) |
| `app/portfolio/reval.py` | `timeseries(snapshots, prices, from_date, to_date)` | `two-snapshot-period` | `golden/engine_timeseries_twosnap.json` | Each point's `total_value >= 0`; length == (to_date - from_date).days + 1 when snapshots cover period |
| `app/engine/recurring/` | Full detect pipeline (`detect_recurring(transactions)`) | `recurring-monthly-rent` | `golden/engine_recurring_monthly.json` | Rules have confidence ∈ [0,1]; each rule's frequency is a known value |
| `app/portfolio/statement_parser.py` | `parse_investment_statement(text)` (Gemini mocked) | `statement-fidelity-text` | `golden/engine_statement_parser.json` | Statement import tie-out (§6); all required keys present |

### 4b. MCP Tools

All 20 tools registered in `backend/app/mcp/server.py`. One test file:
`backend/tests/evals/backend/test_tools_mcp.py`.

| Tool name | Function in tools.py | Input fixture id | Golden output | Edge cases tested |
|---|---|---|---|---|
| `get_transactions` | `get_transactions` | `transactions-date-range` | `golden/tool_get_transactions.json` | empty result; category filter; description_pattern match; amount bounds |
| `get_spending_by_category` | `get_spending_by_category` | `transactions-date-range` | `golden/tool_spending_by_category.json` | all-positive transactions excluded; zero-spend period |
| `detect_transfers` | `detect_transfers` | `transfers-zelle-venmo` | `golden/tool_detect_transfers.json` | no transfers; keyword only; round-amount only; categorized-as-transfer |
| `update_transaction_category` | `update_transaction_category` | `single-transaction` | `golden/tool_update_category.json` | invalid category returns `{ok: false, error: "invalid_category"}`; txn not found |
| `compare_spending_periods` | `compare_spending_periods` | `two-month-comparison` | `golden/tool_compare_spending.json` | period with zero spend in one window (pct_change = null) |
| `bulk_recategorize` | `bulk_recategorize` | `bulk-venmo-txns` | `golden/tool_bulk_recategorize.json` | dry_run=true never updates; no matches returns empty matched list |
| `rescan_transfers` | `rescan_transfers` | `transfers-window` | `golden/tool_rescan_transfers.json` | empty window; window_days override |
| `get_snapshot` | `get_snapshot` | `single-account-2-holdings` | `golden/tool_get_snapshot.json` | no accounts returns zero snapshot |
| `score_goal` | `score_goal` | `feasibility-basic` | `golden/tool_score_goal.json` | goal_id not found; ambiguous name returns error with matches list |
| `simulate_decision` | `simulate_decision_tool` | `simulation-car-purchase` | `golden/tool_simulate_decision.json` | zero upfront_cost + zero monthly_delta |
| `monte_carlo` | `monte_carlo_tool` | `monte-carlo-30yr` | `golden/tool_monte_carlo.json` | years <= 0 returns error; both initial_portfolio and monthly_contribution = 0 returns error |
| `list_recurring_rules` | `list_recurring_rules` | `recurring-monthly-rent` | `golden/tool_list_recurring.json` | min_monthly_amount filter; frequency filter; status filter; no rules |
| `update_goal` | `update_goal` | `feasibility-basic` | `golden/tool_update_goal.json` | goal not found; ambiguous name; no-op (no fields passed) |
| `delete_goal` | `delete_goal` | `feasibility-basic` | `golden/tool_delete_goal.json` | goal not found; idempotent (already inactive) |
| `find_similar_goal` | `find_similar_goal` | `feasibility-basic` | `golden/tool_find_similar_goal.json` | no existing goals; score < 0.6 is not a duplicate |
| `find_goal_by_name` | `find_goal_by_name` | `feasibility-basic` | `golden/tool_find_goal_by_name.json` | partial match; no match (score < 0.3) returns error + all_goal_names |
| `project_cashflow` | `project_cashflow_tool` | `cashflow-12mo-rsu` | `golden/tool_project_cashflow.json` | months override; no RSU events; no recurring rules |
| `compute_annuity` | `compute_annuity` (no db/user_id) | *(pure math — no Seed needed)* | `golden/tool_compute_annuity.json` | solve_for=months; fv; pmt; annual_rate ≤ 0 error; n > 1200 triggers warning |
| `portfolio_get_holdings` | `portfolio_get_holdings` | `single-account-2-holdings` | `golden/tool_portfolio_holdings.json` | empty portfolio; unowned account_id returns `[{"error": ...}]`; multi-account aggregation |
| `portfolio_get_exposure` | `portfolio_get_exposure` | `etf-with-look-through` | `golden/tool_portfolio_exposure.json` | invalid dimension; cash-only account; unknown ticker in references |
| `portfolio_get_attribution` | `portfolio_get_attribution` | `attribution-mixed-txns` | `golden/tool_portfolio_attribution.json` | no snapshots in window; unowned account_id; macro fields null when FRED mocked empty |

### 4c. REST Endpoints

All 10 routes under `/portfolio`. One test file:
`backend/tests/evals/backend/test_endpoints_portfolio.py`. Use `fastapi.testclient.TestClient`
with `app.dependency_overrides[get_current_user]` set to a fixed fake user. Patch
`get_admin_db` to return a MagicMock wired to fixture data.

| Method + path | Handler | Input fixture | Expected response shape | Pydantic schema validated |
|---|---|---|---|---|
| `POST /portfolio/sync/plaid` | `sync_plaid` | *(no Seed needed; mock Plaid client)* | `{"snapshots_written": int}` | None (raw dict) |
| `POST /portfolio/snapshot/manual` | `create_manual_snapshot` | `single-holding` | `schemas.SnapshotOut` | `schemas.SnapshotOut.model_validate(resp.json())` |
| `GET /portfolio/holdings` | `get_holdings` | `single-account-2-holdings` | `List[schemas.HoldingOut]` | each item: `schemas.HoldingOut.model_validate(h)` |
| `GET /portfolio/exposure` | `get_exposure` | `etf-with-look-through` | `List[schemas.ExposureSlice]` | each item: `schemas.ExposureSlice.model_validate(s)` |
| `GET /portfolio/timeseries` | `get_timeseries` | `two-snapshot-period` | `schemas.TimeSeriesResponse` | `schemas.TimeSeriesResponse.model_validate(resp.json())` |
| `GET /portfolio/attribution` | `get_attribution` | `attribution-mixed-txns` | `schemas.AttributionResult` | `schemas.AttributionResult.model_validate(resp.json())` |
| `GET /portfolio/summary` | `get_summary` | `single-account-2-holdings` | `schemas.PortfolioSummary` | `schemas.PortfolioSummary.model_validate(resp.json())` |
| `POST /portfolio/import/statement` | `import_statement_preview_text` | *(Gemini mocked; raw text input)* | `schemas.StatementPreview` | `schemas.StatementPreview.model_validate(resp.json())` |
| `POST /portfolio/import/statement/file` | `import_statement_preview_file` | *(Gemini mocked; multipart file upload)* | `schemas.StatementPreview` | `schemas.StatementPreview.model_validate(resp.json())` |
| `POST /portfolio/import/statement/confirm` | `import_statement_confirm` | `single-holding` | `schemas.SnapshotOut` | `schemas.SnapshotOut.model_validate(resp.json())` |

---

## 5. Golden Snapshot Management

### 5.1 Library decision: use `syrupy`, not a custom implementation

**Earlier drafts proposed a custom `--regenerate-golden` flag + `DRIFT_ALLOWED` dict in `conftest.py`.** That reinvents what [`syrupy`](https://github.com/syrupy-project/syrupy) already provides:

| Feature | Custom (rejected) | `syrupy` |
|---|---|---|
| Regenerate flag | `--regenerate-golden` (custom) | `--snapshot-update` (built-in) |
| Field exclusion | `DRIFT_ALLOWED` dict (custom) | `serializer.filter` (built-in) |
| JSON snapshots | rolled in conftest | `extension_class=JSONSnapshotExtension` (built-in) |
| Snapshot naming | tied to test fn name (custom) | tied to test fn name (built-in) |
| Maintenance | ours | upstream |

**Adopting `syrupy` removes ~100 lines of conftest extensions** and inherits years of edge-case fixes.

Add to `requirements.txt`: `syrupy>=4.6`.

### 5.2 Pattern

Tests use `syrupy`'s `snapshot` fixture:

```python
from syrupy.extensions.json import JSONSnapshotExtension

@pytest.fixture
def snapshot_json(snapshot):
    return snapshot.use_extension(JSONSnapshotExtension)

def test_compute_snapshot_basic(seed_single_brokerage, snapshot_json):
    result = compute_snapshot(seed_single_brokerage.accounts)
    assert result == snapshot_json  # asserts against existing snapshot OR creates one with --snapshot-update
```

### 5.3 Snapshot files

- Location: alongside the test file in a `__snapshots__/` directory (syrupy default).
- Format: JSON with deterministic key ordering.
- Regenerate: `pytest --snapshot-update backend/tests/evals/backend/`.

**Missing snapshot behavior (deterministic, by syrupy):** the first run of a new test without a snapshot file creates the file at the location and *passes*. This is `syrupy`'s default and matches industry-standard snapshot testing. **The first run of a new test must therefore be reviewed by a human before merge** — diff inspection is the gate, not the assertion. Reviewers must look at the new snapshot file in the PR diff and confirm the data is intentional.

To prevent silent first-run passes from masking real bugs, **CI must fail when snapshot files are created during a CI run** (`pytest --snapshot-update` is for local dev only). Configure via:

```python
# conftest.py
def pytest_collection_finish(session):
    if os.getenv("CI") and "--snapshot-update" in session.config.invocation_params.args:
        pytest.fail("--snapshot-update is forbidden in CI. Generate snapshots locally and commit.")
```

### 5.4 Field exclusion (DRIFT_ALLOWED equivalent)

Use `syrupy.matchers.path_type` to ignore timestamps, UUIDs, and other generated fields:

```python
from syrupy.matchers import path_type

assert result == snapshot_json(matcher=path_type({"created_at": (str,)}))
```

### 5.5 Diff review

Golden changes require a written rationale in the PR description — e.g.:
`__snapshots__/test_engine_attribution.ambr: market bucket updated because rounding
precision changed from 0 to 2dp (PR #XYZ)`. Reviewers confirm the change is intentional.

---

## 5.6 Tag for engine exceptions

Distinguish "golden mismatch" (the engine ran, output drifted) from "engine raised" (the engine crashed). Different remediation paths:

| Tag | When |
|---|---|
| `[GOLDEN-DRIFT]` | Engine ran successfully but output differs from snapshot. Either intentional (regenerate) or a bug. |
| `[ENGINE-EXCEPTION]` | Engine raised an unhandled exception. Always a bug; investigate before regenerating. |

Test runner detects these distinctly via try/except wrapping the engine call.

---

## 6. Invariant Catalog

### 6.0 Hypothesis configuration (prerequisite)

Property-based invariant tests use `hypothesis`. Add to `requirements.txt`: `hypothesis>=6.100`.

**Settings profiles** — two profiles, fast for CI, thorough for nightly:

```python
# backend/tests/evals/backend/conftest.py
from hypothesis import settings, Verbosity
import os

settings.register_profile("fast", max_examples=50, deadline=2000, verbosity=Verbosity.normal)
settings.register_profile("thorough", max_examples=500, deadline=10000, verbosity=Verbosity.verbose)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "fast"))
```

CI uses `fast` (default). Nightly uses `HYPOTHESIS_PROFILE=thorough`.

**Strategy library** — hypothesis strategies live in `backend/tests/evals/backend/strategies.py`. Each invariant below cites a strategy by name; the bodies are authored once in `strategies.py` and reused. Example for attribution:

```python
# strategies.py
import string
from datetime import date
from hypothesis import strategies as st

@st.composite
def attribution_transaction_strategy(draw):
    txn_type = draw(st.sampled_from(["buy", "sell", "dividend", "interest", "fee",
                                      "transfer_in", "transfer_out", "split", "reinvest"]))
    amount = draw(st.floats(min_value=-100_000, max_value=100_000,
                            allow_nan=False, allow_infinity=False))
    return {
        "type": txn_type,
        "amount": round(amount, 2),
        "date": draw(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))),
        "ticker": draw(st.one_of(st.none(),
                       st.text(alphabet=string.ascii_uppercase, min_size=1, max_size=5))),
    }

attribution_transactions = st.lists(attribution_transaction_strategy(), min_size=0, max_size=20)
```

When an engine signature changes, the strategy MUST be updated in the same PR.

**Failure interpretation** — when a property test fails, hypothesis prints the minimal counterexample. Reproduce locally with `@example(...)` pinned to the failing input; leave the `@example` in place after fixing as a regression marker.

---

### Invariants



Each invariant has: formula, tolerance, fixture(s) that exercise it, and what a failure means.
Tests for invariants live in `backend/tests/evals/backend/test_invariants_portfolio.py`.

### I1 — Attribution identity

**Formula:** `end_value - start_value == contributions + withdrawals + dividends + trades + market + unattributed`

**Tolerance:** `1e-9` (integer-accurate arithmetic with rounding at output only)

**Assertion:**
```python
decomp = compute_attribution(start_value=sv, end_value=ev, transactions=txns)
lhs = decomp["end_value"] - decomp["start_value"]
rhs = (decomp["contributions"] + decomp["withdrawals"] + decomp["dividends"]
       + decomp["trades"] + decomp["market"] + decomp["unattributed"])
assert lhs == pytest.approx(rhs, abs=1e-9)
```

**Fixtures:** `attribution-mixed-txns`, `unattributed-residual`

**Failure means:** A bucket is double-counted or missing; the decomposition is inconsistent.

---

### I2 — Exposure percentages sum to 100%

**Formula:** `Σ(slice.percent) == 100.0` for any dimension (asset_class / sector / region)

**Tolerance:** `0.5 pp` absolute (to account for floating-point rounding across many holdings)

**Assertion:**
```python
slices = compute_exposure(holdings, refs, dimension=dim)
total_pct = sum(s["percent"] for s in slices)
assert abs(total_pct - 100.0) <= 0.5
```

**Fixtures:** `etf-with-look-through`, `single-holding`, `cash-only-account`

**Failure means:** Weights were applied incorrectly or a residual was lost.

---

### I3 — Look-through residual non-negative

**Formula:** For every ETF with look_through: `residual = 1.0 - Σ(item.weight) >= 0`

**Tolerance:** `0` (must be exactly >= 0 before rounding)

**Assertion:**
```python
for ref in refs.values():
    if ref.get("look_through"):
        total_weight = sum(item["weight"] for item in ref["look_through"])
        assert total_weight <= 1.0 + 1e-9, f"{ref['ticker']} look_through weights sum to {total_weight}"
```

**Fixtures:** `etf-with-look-through`

**Failure means:** ETF weight data is corrupt; a sub-allocation would be double-counted.

---

### I4 — Reval correctness (present prices)

**Formula:** `revalue_at(holdings, as_of, prices, cash) == cash + Σ(qty × close_price(as_of))`
when every holding has an exact price on `as_of`.

**Tolerance:** `1e-6` relative

**Assertion:**
```python
expected = cash + sum(float(h["quantity"]) * prices[(h["ticker"], as_of)] for h in holdings)
actual = revalue_at(holdings, as_of, prices, cash)
assert actual == pytest.approx(expected, rel=1e-6)
```

**Fixtures:** `single-holding`, `single-account-2-holdings`

**Failure means:** Holdings are being double-counted or prices are looked up incorrectly.

---

### I5 — Snapshot total consistency

**Formula:** `snapshot.total_value == snapshot.cash_value + Σ(holding.market_value)`

**Tolerance:** `1e-6` relative

**Assertion:**
```python
snap = get_latest_snapshot(db, account_id=aid)
computed = snap["cash_value"] + sum(float(h["market_value"]) for h in snap["holdings"])
assert float(snap["total_value"]) == pytest.approx(computed, rel=1e-6)
```

**Fixtures:** `single-account-2-holdings`, `cash-only-account`

**Failure means:** The `total_value` field was set independently of the holdings sum; they
have drifted (Plan 2 bug class — patched in the portfolio migration).

---

### I6 — Statement import tie-out

**Formula:** `cash_value + Σ(holding.qty × holding.price) ≈ total_value_reported` within 1%,
when `total_value_reported` is present in the parser output.

**Tolerance:** `1%` relative

**Assertion:**
```python
parsed = parse_investment_statement(statement_text)  # Gemini mocked
if parsed.get("total_value_reported") is not None:
    computed = parsed["cash_value"] + sum(
        float(h["quantity"]) * float(h["price"]) for h in parsed["holdings"]
    )
    ratio = abs(computed - parsed["total_value_reported"]) / parsed["total_value_reported"]
    assert ratio <= 0.01
```

**Fixtures:** `statement-fidelity-text` (golden Gemini response with known total)

**Failure means:** Parser extracted wrong quantities or prices; the UI tie-out warning logic
will fire incorrectly or fail to fire.

---

### I7 — Monte Carlo determinism

**Formula:** `run_monte_carlo(..., seed=129)` → identical percentile outputs across N runs.

**Tolerance:** exact equality (same numpy seed → same floats)

**Assertion:**
```python
results = [run_monte_carlo(initial_portfolio=100_000, monthly_contribution=500, years=30)
           for _ in range(5)]
for r in results[1:]:
    assert r["p50"] == results[0]["p50"]
    assert r["p10"] == results[0]["p10"]
    assert r["p90"] == results[0]["p90"]
```

**Fixtures:** `monte-carlo-30yr`

**Failure means:** numpy seed is not being set (or is being set after use), breaking the
"same inputs → same result" guarantee that makes the chat advisor reliable.

---

### I8 — Plaid sign convention

**Formula:** `map_plaid_investment_transactions` returns signed cash impact;
`Σ(amount for type in (transfer_in, dividend, interest)) - Σ(abs(amount) for type in (transfer_out, buy))`
== net cash flow for the period.

**Tolerance:** `1e-6`

**Assertion:** Covered in `test_plaid_sync.py`; include in Spec B invariant suite by importing
and re-asserting against a fixed fixture of Plaid-format txns.

**Fixtures:** `plaid-txn-batch`

**Failure means:** Cash flows will be inverted in the attribution decomposition.

---

### I9 — Idempotent Plaid-txn dedupe

**Formula:** Calling `create_plaid_snapshot` twice with identical payload inserts txn rows
exactly once (deduplicated via `plaid_investment_transaction_id` unique constraint).

**Tolerance:** count check (exact equality)

**Assertion:**
```python
# Call with real Supabase test client (skip against MagicMock — constraint is DB-enforced)
create_plaid_snapshot(db, user_id=uid, ...)
create_plaid_snapshot(db, user_id=uid, ...)
rows = db.table("investment_transactions").select("id").eq("user_id", uid).execute().data
assert len(rows) == N_EXPECTED_TXNS  # not 2×
```

**Fixtures:** `plaid-txn-batch` (live-DB test; marked `@pytest.mark.live_db`)

**Failure means:** Portfolio attribution will double-count flows on Plaid refresh.

---

### I10 — Cost-basis subset

**Formula:** When `cost_basis` is present on a holding:
`unrealized_gain == market_value - cost_basis`; when `cost_basis` is null, `unrealized_gain`
must also be null.

**Tolerance:** `1e-2` absolute (holdings values rounded to 2 decimal places)

**Assertion:**
```python
for h in snap["holdings"]:
    if h.get("cost_basis") is not None:
        assert h["unrealized_gain"] == pytest.approx(
            h["market_value"] - h["cost_basis"], abs=0.01
        )
    else:
        assert h.get("unrealized_gain") is None
```

**Fixtures:** `mixed-basis-trades`, `single-holding`

**Failure means:** Unrealized gain is fabricated or inconsistent with cost basis; the UI
P&L display will show wrong numbers.

---

## 7. Differential Test Catalog

Tests live in `backend/tests/evals/backend/test_differential.py`. Each test calls the pure
MCP tool function **and** the equivalent REST handler function (bypassing HTTP) with an
identical MagicMock DB returning the same fixture data, then asserts field-by-field equality.

### D1 — Holdings

| | |
|---|---|
| MCP | `portfolio_get_holdings(db, user_id, account_id=aid)` |
| REST | `get_holdings(account_id=UUID(aid), user=fake_user)` (awaited) |
| Fields compared | `ticker`, `quantity`, `market_value`, `percent`, `cost_basis` |
| Known difference | `percent` precision: MCP rounds to 2dp, REST rounds to 4dp — assert 2dp agreement |
| Fixture | `single-account-2-holdings` |

```python
mcp_result = portfolio_get_holdings(db, user_id, account_id=aid)
rest_result = await get_holdings(account_id=UUID(aid), user=fake_user)
for mcp_h, rest_h in zip(
    sorted(mcp_result, key=lambda h: h["ticker"]),
    sorted([h.model_dump() for h in rest_result], key=lambda h: h["ticker"]),
):
    assert mcp_h["ticker"] == rest_h["ticker"]
    assert mcp_h["market_value"] == pytest.approx(rest_h["market_value"], rel=1e-6)
```

---

### D2 — Exposure

| | |
|---|---|
| MCP | `portfolio_get_exposure(db, user_id, dimension="asset_class")` |
| REST | `get_exposure(dim="asset_class", user=fake_user)` (awaited) |
| Fields compared | `label`, `market_value`, `percent` |
| Known difference | None |
| Fixture | `etf-with-look-through` |

```python
mcp_slices = portfolio_get_exposure(db, user_id, dimension="asset_class")
rest_slices = [s.model_dump() for s in await get_exposure(dim="asset_class", user=fake_user)]
assert sorted(mcp_slices, key=lambda s: s["label"]) == pytest.approx(
    sorted(rest_slices, key=lambda s: s["label"]), rel=1e-6
)
```

---

### D3 — Attribution (including macro context)

| | |
|---|---|
| MCP | `portfolio_get_attribution(db, user_id, from_date=fd, to_date=td)` |
| REST | `get_attribution(from_date=fd, to_date=td, user=fake_user)` (awaited) |
| Fields compared | all decomp buckets + `macro_context` fields |
| Known difference | **None.** Commit `155810e` (`fix(portfolio): address Plan 4 code review findings`, 2026-05-08) aligned the MCP tool's macro computation with the REST router. Both now use `end - start` for `ten_year_yield_change_bps` and `_latest_value(series, to_date)` for `cpi_yoy_at_end`. **Assert EQUALITY for all macro fields.** |
| Fixture | `attribution-mixed-txns` |

```python
mcp_result = portfolio_get_attribution(db, user_id, from_date=fd, to_date=td)
rest_result = (await get_attribution(from_date=fd, to_date=td, user=fake_user)).model_dump()
# Decomp buckets
for key in ("contributions", "withdrawals", "dividends", "trades", "market", "unattributed"):
    assert mcp_result[key] == pytest.approx(rest_result[key], abs=1e-9)
# Macro context — must be equal (I1 fix landed)
mcp_macro = mcp_result["macro_context"]
rest_macro = rest_result["macro_context"]
assert mcp_macro["ten_year_yield_change_bps"] == pytest.approx(
    rest_macro["ten_year_yield_change_bps"], abs=0.5
)
assert mcp_macro["cpi_yoy_at_end"] == pytest.approx(rest_macro["cpi_yoy_at_end"], rel=1e-6)
assert mcp_macro["spy_period_return_pct"] == pytest.approx(
    rest_macro["spy_period_return_pct"], rel=1e-6
)
```

If any of these assertions start failing after a future refactor, tag the failure
`[DIFFERENTIAL-MISMATCH]` and re-examine whether `_yield_change_bps_from_series` in
`tools.py` and `_yield_change_bps` in `router.py` have diverged again.

---

### D4 — Error parity (across all three differential pairs)

Differential tests so far check **success-path equality**: same input → same output. They do **not** check that both surfaces fail in the same way on bad input. Without an error-parity check, a refactor where the MCP tool starts raising on `account_id=None` while the REST handler still returns 404 would slip through unnoticed — and users would see different failures depending on which surface they hit.

Each MCP↔REST pair gets one additional test asserting **error parity** on a known-bad input:

```python
def test_holdings_error_parity_on_unowned_account():
    """Both MCP and REST surfaces must respond consistently on an unowned account_id."""
    fake_db = MagicMock()
    # accounts query returns empty — neither user owns this account
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value.in_.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    mcp_result = portfolio_get_holdings(fake_db, user_id="u-A", account_id="other-uuid")
    assert mcp_result == [{"error": "account not found"}]

    with pytest.raises(HTTPException) as rest_exc:
        await get_holdings(account_id=UUID("other-uuid"), user=fake_user)
    assert rest_exc.value.status_code == 404

    # The shapes differ (list-with-error-dict vs HTTPException), but the SEMANTIC
    # behavior must agree: both surfaces refuse to serve data for an unowned account.
    # If MCP starts succeeding (or REST starts erroring on a different code), this
    # test catches the divergence.
```

Apply the same pattern to D2 (exposure with bad `dim`) and D3 (attribution with `from_date >= to_date`). Document the expected error payload shape per surface explicitly — different failure shapes are acceptable as long as both surfaces actually fail.

---

## 8. Edge Case Fixture Catalog

All fixtures live in `backend/tests/evals/shared/reference_data.json` (or are described there
as named `Seed` configurations). Every test author should be aware of these:

| Fixture id | Description | Key properties |
|---|---|---|
| `empty-portfolio` | User has no brokerage/retirement accounts | All portfolio endpoints return empty list or zero-valued response |
| `single-holding` | One brokerage account, one snapshot, one ticker (NVDA×10), no txns | Exercises cost-basis present path; exposes ratio / percent edge case when total == market_value of only holding |
| `etf-with-look-through` | VOO with 2 top-10 entries (AAPL 7%, MSFT 6%); residual 87% | Exercises look-through logic in exposure.py; residual must be non-negative (I3) |
| `cash-only-account` | Investment account with cash_value > 0 but zero holdings | Snapshot total consistency (I5) with no holdings; exposure returns empty or all-cash slice |
| `account-with-no-txns` | Snapshot exists, investment_transactions table is empty for this account | Attribution: all change goes to market bucket; unattributed = 0 |
| `cross-snapshot-stock-split` | Two snapshots, quantity doubles between them (e.g. 10 → 20 NVDA) | Tests that reval.timeseries uses each snapshot's own quantities, not a fixed qty |
| `mixed-basis-trades` | Sells with `cost_basis_at_sell` on some rows, null on others | Attribution: `trades_has_basis=False` path; I10 cost-basis subset invariant |
| `unattributed-residual` | Two snapshots where `end - start ≠ recorded flows + reval-derived market` | Attribution identity still holds (I1); unattributed ≠ 0 only when `clean_market_estimate` is provided |

---

## 9. Schema Validation

Every test that calls an API function (MCP tool or REST handler) must round-trip the result
through its Pydantic schema. Pattern:

```python
# After calling a REST endpoint:
resp = client.get("/portfolio/attribution", params={"from_date": "...", "to_date": "..."})
assert resp.status_code == 200
parsed = schemas.AttributionResult.model_validate(resp.json())
assert parsed.market is not None  # field-level assertions on the typed object

# After calling an MCP tool function directly:
raw = portfolio_get_attribution(db, user_id, from_date=fd, to_date=td)
# MCP returns a plain dict — use a local dataclass or TypedDict; or validate non-portfolio
# fields via a hand-written validator. For portfolio tools that share the schema:
parsed = schemas.AttributionResult.model_validate(raw)
```

Schemas that must be validated in this way:

| Schema | Used by |
|---|---|
| `schemas.SnapshotOut` | `POST /portfolio/snapshot/manual`, `POST /portfolio/import/statement/confirm` |
| `schemas.HoldingOut` | `GET /portfolio/holdings`, `portfolio_get_holdings` |
| `schemas.ExposureSlice` | `GET /portfolio/exposure`, `portfolio_get_exposure` |
| `schemas.TimeSeriesResponse` | `GET /portfolio/timeseries` |
| `schemas.AttributionResult` | `GET /portfolio/attribution`, `portfolio_get_attribution` |
| `schemas.PortfolioSummary` | `GET /portfolio/summary` |
| `schemas.StatementPreview` | `POST /portfolio/import/statement`, `POST /portfolio/import/statement/file` |

---

## 10. Failure-Mode Tags

Backend eval reports must tag each failure with exactly one of:

| Tag | When to use |
|---|---|
| `[GOLDEN-DRIFT]` | Golden snapshot doesn't match actual output. If intentional (engine change) → regenerate + write PR rationale. If unintentional → this is the bug. |
| `[INVARIANT-VIOLATION]` | A mathematical identity is broken (see §6). Example: attribution buckets don't sum to period change. |
| `[DIFFERENTIAL-MISMATCH]` | MCP tool and REST endpoint returned different values for the same input (see §7). |
| `[SCHEMA-MISMATCH]` | Pydantic `model_validate` raised `ValidationError` — a field is missing, null when it shouldn't be, or an extra field appeared. |
| `[FIXTURE-CONTAMINATION]` | A test modified shared DB state and caused another test to fail. Tag the downstream failure; root-cause is the upstream test that failed to clean up. |

---

## 11. Run Command + Cadence

```bash
# Run all Spec B tests
pytest backend/tests/evals/backend/ -v

# Regenerate golden snapshots (after intentional engine changes)
pytest --regenerate-golden backend/tests/evals/backend/

# Run only invariant tests
pytest backend/tests/evals/backend/test_invariants_portfolio.py -v

# Run only differential tests
pytest backend/tests/evals/backend/test_differential.py -v
```

**Cadence:** Runs in CI on every commit to `main` and every PR. Target: full suite completes
in < 30 seconds (all tests use MagicMock DB; no network I/O except the optional
`@pytest.mark.live_db` tests which are skipped in CI unless `SUPABASE_TEST_URL` is set).

---

## 12. Out of Scope

The following are explicitly **not** tested in this spec:

- **LLM judgment quality** — whether Gemini cites the right numbers, pushes back on bad ideas,
  or narrates attribution correctly. That is Spec C.
- **UI rendering** — whether React components display the engine output. That is Spec A.
- **Live external services** — FRED API (mocked with canned dict), yfinance (mocked), Plaid
  sandbox (mocked Plaid client). Live integration is validated by Plan 2 / Plan 3 / Plan 4
  smoke tests, not this eval.
- **End-to-end HTTP stack** — TestClient tests verify handler logic; full ASGI middleware
  stack (auth JWT validation, CORS, rate limits) is out of scope for this spec.

---

## 13. Migration Table — Existing Test Classification

Audit of `backend/tests/portfolio/`, `backend/tests/mcp/`, and `backend/tests/advisor/`.
Disposition of each test file relative to Spec B standards (deterministic, no LLM, asserts
against fixtures):

### `backend/tests/portfolio/`

| File | Disposition | Reason |
|---|---|---|
| `test_attribution.py` | **kept-as-is** | Pure-Python, deterministic, asserts on exact dict values. Already meets Spec B inline-assert standard; could optionally be promoted to golden format. |
| `test_exposure.py` | **kept-as-is** | Pure-Python, deterministic, asserts on exact output. Same as above. |
| `test_reval.py` | **kept-as-is** | Pure-Python, deterministic. All test cases are correct Spec B candidates. |
| `test_snapshots.py` | **kept-as-is** | Uses MagicMock DB; asserts on struct shape. No LLM. |
| `test_router.py` | **refactor-to-golden** | Uses TestClient + MagicMock correctly, but asserts inline on hard-coded response values. Promoting to golden snapshots would make schema drift visible. |
| `test_statement_parser.py` | **kept-as-is** | Gemini is mocked; asserts on parsed dict. Correct pattern for Spec B. |
| `test_fred.py` | **kept-as-is** | FRED fetch is mocked; pure logic test. |
| `test_reference.py` | **kept-as-is** | DB mock + price lookup logic. No LLM. |
| `test_plaid_sync.py` | **refactor-to-golden** | Tests Plaid mapping logic but uses inline asserts on raw dicts; golden format would catch sign-convention regressions more cleanly. |

### `backend/tests/mcp/`

| File | Disposition | Reason |
|---|---|---|
| `test_tools.py` | **refactor-to-golden** | Deterministic, MagicMock DB, good coverage of tool wrappers. Inline asserts should be promoted to golden snapshots so future tool output changes are visible. |
| `test_engine_tools.py` | **refactor-to-golden** | Tests engine-wrapper MCP tools with patched `_monthly_income_expenses`. Solid structure; needs golden promotion + portfolio tool coverage added. |

### `backend/tests/advisor/`

| File | Disposition | Reason |
|---|---|---|
| `test_context.py` | **kept-as-is** | Tests the financial context builder (pure Python + DB mock). No LLM calls. Spec B compatible. |
| `test_context_portfolio_block.py` | **kept-as-is** | Portfolio block rendering test; deterministic. |
| `test_context_recurring.py` | **kept-as-is** | Recurring block rendering; deterministic. |
| `test_displayable_table.py` | **kept-as-is** | Table rendering utility; deterministic. |
| `test_system_prompt.py` | **kept-as-is** | Prompt string builder; deterministic. |
| `test_validators.py` | **kept-as-is** | Input validators; deterministic. |
| `test_findings_start.py` | **kept-as-is** | Findings detection logic; deterministic. |
| `test_recurring_review.py` | **kept-as-is** | Recurring rule review logic; deterministic. |
| `test_resilience.py` | **migrate-to-spec-c** | Tests advisor retry/recovery behavior which involves LLM-side assumptions about response content. |
| `test_summarize_tool_result.py` | **migrate-to-spec-c** | Asserts on prose summarization quality of tool results — judgment, not determinism. |

---

## 14. Meta-tests for the Eval Harness

The Spec B harness (`syrupy` integration, hypothesis strategies, differential helpers, the `/eval/health` endpoint shared with Spec A, the Seed fixture wrapper) is itself code that runs in CI. Without unit tests, a harness bug — a `path_type` matcher accidentally excluding a real field, a hypothesis strategy generating `nan`, a differential helper passing the wrong mock to the REST path — produces false passes that look like model regressions. Same gap pattern as Spec A §14 and Spec C §16.

### 14.1 Coverage targets

Every public function in the harness has at least one test. Tests are deterministic, mock-only, and run < 5 seconds total.

### 14.2 Test files (NEW)

```
backend/tests/evals/backend/test_harness.py (NEW)
  ├── test_syrupy_integration_creates_snapshot_on_first_run
  ├── test_syrupy_path_type_matcher_excludes_timestamps
  ├── test_syrupy_path_type_matcher_excludes_uuids
  ├── test_syrupy_assert_fails_on_real_diff
  ├── test_ci_refuses_snapshot_update_flag
  ├── test_seed_fixture_function_scope_cleans_between_tests
  ├── test_engine_exception_tag_distinguished_from_golden_drift
  ├── test_differential_helper_delivers_same_mock_to_both_paths
  ├── test_differential_helper_field_by_field_with_tolerance
  ├── test_error_parity_helper_both_paths_fail
  ├── test_error_parity_helper_xfails_when_only_one_fails
  └── test_pytest_marker_live_db_skipped_without_env

backend/tests/evals/backend/test_strategies.py (NEW — meta-tests for hypothesis strategies)
  ├── test_attribution_transaction_strategy_generates_valid_dict
  ├── test_attribution_transaction_strategy_no_nan
  ├── test_exposure_holdings_strategy_market_value_non_negative
  ├── test_reval_prices_strategy_close_positive
  └── test_snapshot_strategy_total_value_consistent_with_holdings
```

### 14.3 Acceptance

- All tests in `test_harness.py` and `test_strategies.py` pass under standard pytest.
- Suite runs in < 5 seconds (no real DB, no live API calls).
- A failing meta-test is treated as a hard CI gate — the eval harness is broken until fixed.

### 14.4 What meta-tests don't cover

- Engine math correctness (that's what the rest of Spec B measures).
- LLM behavior (Spec C).
- UI rendering (Spec A).

These meta-tests verify the harness, not the system under test.

---

## 15. Phased Rollout

Spec B is large: 11 engine modules + 20 MCP tools + 10 REST endpoints + 10 invariants + 4 differential tests = ~50+ test functions, plus the meta-test suite. Do **not** attempt to land all of it in one PR. Phase the rollout:

- **Phase 1 (the gate):** harness + meta-tests (§14) + ONE engine module + ONE MCP tool + ONE invariant + ONE differential pair (D1: holdings) + the syrupy adoption + the `hypothesis` dependency add. Verifies the harness works end-to-end. ~1-2 days of focused work.
- **Phase 2:** remaining 10 engine modules + remaining 19 MCP tools (parallelizable across multiple PRs).
- **Phase 3:** remaining 9 endpoints + remaining 9 invariants + remaining 3 differential pairs.
- **Phase 4:** migration of existing tests per §13 (refactor-to-golden batch by file).

Phase 1 is the single sequential gate; Phases 2-4 can parallelize. Each phase's PR includes a one-line note in the description: "Spec B Phase N — see docs/superpowers/specs/2026-05-09-eval-backend-spec.md §15."

---

## Prerequisites: Testability Gaps

The following invariants or behaviors **cannot be fully tested today** and require upstream
work before test code can be written:

1. **Stock split handling** (`cross-snapshot-stock-split` fixture): `investment_transactions`
   has a `split` type, but `compute_attribution` ignores split rows (comment in attribution.py:
   `# split: ignore for cash-impact attribution; reflected in the next snapshot's qty`). The
   reval engine uses whatever qty is in the snapshot. A rigorous split test needs a defined
   `qty_split_factor` field on `investment_transactions` rows so the split event can be
   verified independently of the snapshot delta. Until that field exists, the cross-snapshot
   stock-split fixture can only test that attribution doesn't crash — not that it attributes
   the split correctly.

2. **Idempotent `investment_transactions` upsert** (I9): The `investment_transactions` table
   has no composite unique constraint on `(account_id, date, type, ticker, amount)` that would
   allow a true upsert dedup for manually-sourced or statement-imported rows. The unique
   constraint `plaid_investment_transaction_id` only covers Plaid-sourced rows. Until a
   migration adds the composite constraint, I9 can only be tested for the Plaid path.

3. **`hypothesis` library**: Not in `requirements.txt`. Must be added before property-based
   invariant tests can run. Suggested addition: `hypothesis>=6.100`.

4. **`--regenerate-golden` pytest option**: Does not exist yet. Requires a `conftest.py`
   implementation in `backend/tests/evals/backend/` before the golden management workflow
   described in §5 is functional.
