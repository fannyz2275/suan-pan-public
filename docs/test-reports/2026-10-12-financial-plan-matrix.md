# Financial plan browser validation — 2026-10-12

## Result

Final combined run: **36 Playwright checks passed** (Chromium via installed
Google Chrome; desktop 1280px and mobile 390px). Added 32 checks; retained four
existing forecast/recurring checks. **248 engine tests and 150 frontend unit tests
passed.** ESLint passed for both added TypeScript files. Mobile forecast capture
was inspected; no page-level overflow was detected.

This is a representative scenario matrix, not proof of every possible financial
plan. Production calculation code required no changes in this run.

## Scenario matrix

Inputs begin with $20,000 cash, $10,000 investments, $5,000 monthly income,
$1,000 rent, $60 internet, and $500 groceries. Unless changed below, investment
returns and contributions are zero; forecast starts November 2026.

| Scenario | Cash after 3 months | Wealth after 12 months |
| --- | ---: | ---: |
| Ordinary household | $30,320 | $71,280 |
| $6,000 wedding, including $2,000 already saved | $24,320 | $65,280 |
| Wedding plus $3,000 travel | $21,320 | $62,280 |
| $15,000 emergency savings reservation | $30,320 | $71,280 |
| Two competing $20,000 savings targets | $30,320 | $71,280 |
| $9,000 payoff target against $4,000 debt | $26,320 | $67,280 |
| $60,000 wedding causing a shortfall | -$29,680 | $11,280 |
| No ongoing income | $15,320 | $11,280 |
| Invest 50% of surplus | $25,160 | $71,280 |
| Invest surplus while protecting $25,000 cash | $25,000 | $71,280 |
| Additional $1,200 annual insurance | $29,120 | $70,080 |
| $2,500 biweekly payroll, anchored October 30 | $30,320 | $76,280 |
| $100 monthly grocery refunds plus internal transfers | $30,620 | $72,480 |
| $3,000 travel derived from memory | $27,320 | $68,280 |
| Empty accounts/history | $0, with missing-data disclosure | $0, with disclosure |

Both widths also exercise date/amount changes, completing an incomplete memory
plan, disabling plans, resetting source values, quarterly recurring payments,
10% deterministic growth over 1/5/10/30 years, stochastic percentile ordering,
fixed-seed repeatability, reload persistence, and unchanged three-month cash
when the horizon increases. Existing checks cover failed writes and recovery.

## Identity map and invariants

| UI surface | Fact / source | Check |
| --- | --- | --- |
| Spending | Selected-period actual transactions | Existing September income/spending reconciliation |
| Recurring | Source per-payment rules | Source amounts/frequency and rescan recovery |
| Assumptions | Real `/engine/forecast` service | Toggles, amounts, frequency, reset, monthly totals |
| Cash/wealth cards and ledger | Same forecast response | Literal scenario expectations and every monthly table cell |
| Goal funding | Shared available cash | Competing target fails; debt payment capped at outstanding balance |
| Chart | Forecast projection | Mobile capture; percentile ordering in source projection |

Across 30 scenario/viewport checks, all 360 monthly rows satisfy cash
conservation and zero-return net-worth conservation. Contributions and debt
payments do not create wealth. Savings reservations do not spend cash. The
biweekly case explicitly checks $7,500 income in April and October 2027.
Edits propagate to totals and outcomes without a manual reload; saved edits
survive reloads. No mutation-propagation gap was observed in these workflows.

## Iteration history

- Initial execution could not find Playwright's downloaded Chromium; switched
  to installed Google Chrome using the existing executable override.
- Corrected test fixture account type from `credit_card` to supported `debt`.
- Corrected sample transaction IDs to UUIDs required by recurring-rule schema.
- Corrected an independent calendar expectation: January has two paychecks;
  April and October have three for the specified 14-day anchor.
- A test-file edit during a running Vite session caused a reload; final run
  used unchanged files throughout.
- Changed the test's month-field interaction to click outside the input:
  Chrome's Tab navigates field segments and had not triggered the save blur.
- Final combined run passed all 36 checks without retries.

## Reproduction

Start the frontend and synthetic server in separate terminals from the project:

```sh
cd frontend
npm run dev -- --host 127.0.0.1
```

```sh
PYTHONPATH=backend .venv/bin/uvicorn tests.forecast_test_server:app --host 127.0.0.1 --port 8099 --no-access-log
```

```sh
cd frontend
CHAT_UI_BROWSER_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npx playwright test e2e/forecast-plans.spec.ts e2e/forecast.spec.ts e2e/recurring-display.spec.ts
```

Omit the executable override when the Playwright Chromium distribution is
installed. The test server is an unauthenticated, local-only harness; never deploy
it. Source data and authentication are intercepted; forecasts execute the real
Python service with synthetic in-memory persistence. No real financial records,
Supabase writes, bank connections, or paid AI calls were used. Live persistence,
other browser engines, tax/inflation/debt-interest models, and automatic retirement
withdrawals remain outside this test scope.
