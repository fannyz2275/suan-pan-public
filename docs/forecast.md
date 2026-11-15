# Shared Cash and Wealth Forecast

## Flow

`Accounts + recurring rules + transaction history + goals + structured memory`
`-> editable assumptions -> monthly ledger -> Monte Carlo -> Plan / advisor tool`

`GET /engine/forecast?months=12` and `PATCH /engine/forecast?months=12` use
`app/engine/forecast_service.py`. The advisor's `get_financial_forecast` tool uses
the same service and saved settings. It does not receive raw transaction history.
The older cash-flow and portfolio-only endpoints remain compatible, but the Plan
view no longer uses their independent projections or client-side goal deductions.

## Assumptions

- Active recurring rules use their per-payment amount and frequency. Monthly
  equivalents use 52/26/24/12/4/2/1 payments per year. Actual forecast months use
  anchored payment schedules, so biweekly income can have three-payment months.
- Residual category estimates use a median across observed elapsed calendar
  months, up to six months, with zero-activity months included after the first
  observed month. Import coverage is not verified. Current/future transactions,
  transfer categories and confirmed transfer statuses are excluded. Positive
  expense-category credits reduce category spending; they are not salary.
- Every active recurring match is removed from residual history, even when its
  forecast assumption is toggled off. Rejected recurring rules do not suppress
  historical spending. Forecast edits do not alter source transactions or rules.
- Life-event targets are full future expenses. `current_progress` is saved money,
  not proof of an already-paid expense. Savings/investment targets earmark cash;
  they are not additional consumption. Debt-payoff events reduce cash and existing
  debt equally, capped at the debt still outstanding.
- Structured memory events have stable note identities, source quotes, optional
  goal links, dates, and costs. The existing idle extraction loop populates these
  from user statements, not assistant suggestions. Partial updates preserve known
  fields; explicit cancellation excludes the event. Two distinct same-label events
  can coexist. Explicit goal links win; otherwise only an unambiguous normalized
  name and compatible date can consolidate a memory event with a saved goal.
- Saved goals are authoritative when linked to memory. Explicit user overrides
  take precedence, including disabled state. Overrides migrate when a memory event
  becomes a saved goal; resetting removes the override rather than resurrecting an
  old alias. Incomplete or past/current-month events are shown but not modeled.

Preferences and overrides use a deterministic user-scoped row in the existing
`user_notes` table. They are excluded from LLM preference compaction. This feature
needs the existing notes schema, but adds no migration. Missing source tables or
failed writes are surfaced as errors rather than silently dropping obligations.

## Accounting

Each month applies investment returns, income and ordinary spending, all scheduled
goals, then investment contributions. Contributions cannot exceed the selected
share of positive monthly surplus or cash above reserves and upcoming commitments.
The default reserve is three months of recurring plus everyday costs. The next
12 months of dated commitments are protected before investing. Earlier goal dates
are processed first, with stable ID ordering for goals due in the same month.

`cash[t] = cash[t-1] + income - spending - life events - debt paid - contributions`

`investments[t] = investments[t-1] + investment gains + contributions`

`net worth[t] = cash[t] + investments[t] + other assets - remaining debt`

Savings reservations do not change net worth. All enabled goals share the same
cash pool, so the same dollar cannot fund two targets. No automatic sales or
retirement withdrawals occur. Negative cash is an unfunded gap, not assumed loan
approval. All goal-funding and cash-shortfall outcomes are conditional on the
entered cash assumptions; only investment returns are stochastic, so cash-only
funding results can be 0% or 100%.

The simulator uses lognormal gross monthly investment returns, 2,000 paths and
seed 129. The annual-return input is an expected nominal return; volatility is
annualized. Changing the horizon preserves the earlier simulated months. Wealth
percentiles are calculated from joint paths, not by summing separate percentiles.

## Limitations

Projection starts next calendar month using latest known balances. Remaining
current-month activity is omitted and balance timestamps may precede today.
There is no tax, inflation, debt-interest, property-growth, or stochastic
income/spending model. Existing non-cash assets stay fixed; RSU vesting is not
added on top of RSU value already included in net worth. Investment and savings
targets are treated as cash reservations, not tax-aware account allocations.
An expense missing from imported records cannot be reliably inferred.

Spending summaries show actual selected-period credits and debits. Forecasts show
recurring schedules plus residual medians, net of expense-category refunds. These
are deliberately different definitions; a historical monthly total need not equal
a forecast monthly equivalent. The source rows and totals are inspectable.

## Validation

From the repository root:

```bash
cd backend
../.venv/bin/python -m pytest tests/engine/test_forecast.py tests/engine/test_forecast_service.py tests/notes/test_extraction.py -q
```

For Playwright, start the frontend normally. In a second terminal, from the root:

```bash
PYTHONPATH=backend .venv/bin/uvicorn tests.forecast_test_server:app --host 127.0.0.1 --port 8099
```

Then run:

```bash
cd frontend
npx playwright test e2e/forecast.spec.ts e2e/forecast-plans.spec.ts e2e/recurring-display.spec.ts
```

The test server is only a synthetic, unauthenticated local harness. Never deploy
it. Playwright intercepts authentication and imported source records but sends
forecast requests to the real Python calculation service. No production database
or paid model call is involved. Desktop/mobile checks compare Spending, recurring
rules, forecast inputs, monthly ledger values, toggles, saved edits, reloads, and
failed-write recovery. Test captures are under `frontend/test-results/`.

The expanded [financial-plan matrix](test-reports/2026-10-12-financial-plan-matrix.md)
covers 15 synthetic household situations plus edits and long-horizon projections
on desktop and mobile.
