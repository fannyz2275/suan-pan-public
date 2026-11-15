# Finance Data Audit

Use this checklist when changing imports, transfers, balances, or financial
summaries. It preserves the useful project checks from the former Claude skill
without requiring a particular assistant, plugin, or tool name.

## Scope and safety

- Identify the affected user, accounts, dates, currencies, and data sources.
- Distinguish a staged import from saved data. Inspect before writing; do not
  silently change signs, merge accounts, or remove suspected duplicates.
- Use anonymized examples in tests and reports. Never commit statements,
  credentials, account identifiers, or private evaluation datasets.
- Check actual schemas and implementation before assuming a field or category.
  Treat missing data as unavailable, not zero.

## Imported rows

- Validate amounts, dates, currency, account ownership, and statement dates.
- Check duplicate imports using source identifiers and account-specific evidence.
  Matching date/amount/description alone is not proof of duplication.
- Distinguish expenses, refunds, income, and transfers. A positive transaction
  in an expense category can be a refund; do not automatically invert it.
- Validate debt conventions at the import boundary. The current snapshot
  subtracts the absolute debt balance; do not blindly invert stored values.
- Flag outliers and missing fields for review rather than inventing replacements.
- Compare account coverage and statement periods before interpreting missing
  payroll, housing, or other expected activity as a behavioral change.

## Reconciliation

- Cash accounts: when opening/closing balances and complete period activity are
  available, compare opening balance plus signed transactions to closing balance.
  Explain discrepancies and the rounding tolerance used.
- Investment accounts: reconcile closing holdings plus separately held cash to
  the reported account value. Count cash already represented in holdings once.
  Do not add investment transaction amounts to closing holdings values.
- Do not apply a cash-only balance equation to investments, property, or RSUs.
  Valuation changes, vesting, and missing price history require separate checks.
- Recompute net worth with `backend/app/engine/snapshot.py::compute_snapshot`.
  Check account inclusion and notional valuations, not just raw balance sums.
- For historical growth, verify starting and ending balance coverage. Keep
  contributions separate from gains; do not invent a decomposition when the
  required balances or activity are missing.

## Transfers and recurring payments

- Equal inflows/outflows alone do not prove an internal transfer. Verify owned
  account endpoints, reciprocal counterparty evidence, currency, and date rules.
- Respect confirmed transfer decisions and recurring-rule corrections/rejections.
- Unmatched transfers can reflect incomplete account coverage. Report that limit
  rather than assuming all transfer rows must sum to zero.
- Check recurring frequency against recorded dates and recent schedule changes.
  Distinguish bi-weekly from twice-monthly. Repeated scans must preserve IDs and
  avoid duplicate rules or inflated occurrence counts.

## Verification and reporting

- Add focused regression tests, then run the affected engine/API suites.
- For UI changes, verify totals across views and test loading, empty, error,
  retry, filtering, and narrow-screen states with anonymized fixtures.
- Trace advisor numbers to deterministic metrics and their definitions. Inspect
  the actual provider payload before making privacy claims; local hosting alone
  does not mean data remains on-device.
- Report each finding with evidence, affected scope, severity, and proposed fix.
  Separate verified defects from missing data, hypotheses, and untested paths.
- Record test failures and external-service limitations explicitly. A mocked
  test does not establish that a live database migration or integration works.
