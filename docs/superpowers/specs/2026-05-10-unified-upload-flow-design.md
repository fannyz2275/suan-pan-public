# Unified Upload Flow — Design + Implementation Plan

**Date:** 2026-05-10
**Branch:** `feat/unified-upload-flow`
**Status:** Approved, in implementation

## Problem

Today the app has two completely different upload modals reachable from the same surfaces:

- Header `+ Import accounts`, Overview empty state, TransferReviewModal `Upload` → `ImportModal` (parses accounts **and** transactions from any file/text, dedupes accounts by `(type, last4|name)`, inserts transactions **without an `account_id`** — orphan rows in the `transactions` table).
- Portfolio tab `Import statement` → `PortfolioImportModal` (requires the user to pre-pick an investment account, writes a portfolio snapshot scoped to that `account_id`).

The Portfolio flow is the better model — it ties data to a concrete account so downstream features (per-account chart, transfer detection, advisor context) have correct provenance. We want every upload entry point to share that mental model.

## Goals

1. Every upload path requires the user to pick (or create) one or more target accounts before parsing.
2. Transactions and snapshots saved through the unified flow always have `account_id` set.
3. Existing entry points (header, empty state, Portfolio tab, TransferReviewModal) keep working — only the modal swaps.
4. Multi-account uploads are supported in one session — one row per account, files per row.
5. After save, run the existing transfer-candidate scan immediately and surface new candidates to the user.

## Non-goals

- Removing Plaid sync or replacing the Plaid Link flow.
- Backfilling `account_id` onto historical orphan transactions.
- Changing the parsers — same `parse_accounts_from_text`, `parse_transactions_from_text`, `parse_investment_statement`.

## Design

### Frontend

One new component `UnifiedImportModal` replaces both `ImportModal` and `PortfolioImportModal`. Optional `initialAccountId` prop pre-fills the first row (used by the Portfolio tab; ignored when opened from the header).

**Upload step (rows):**

- N rows (1..10). Each row = `account_id` picker + multi-file input.
- Account dropdown includes existing accounts (name + type pill) plus a `+ New account…` entry that expands to an inline name + type form and POSTs to `/finance/accounts` immediately, then auto-selects the new account on that row.
- File constraints per row: PDF / CSV / TXT, ≤ 10 MB each, ≤ 5 files per row.
- `Preview` button disabled until every row has both an account and ≥ 1 file.
- Plain-text input mode is dropped (cold start → inline-create + first file upload, or Plaid).
- Plaid section at the bottom of the same modal: existing `PlaidConnectButton` under "Or connect a bank automatically." Plaid bypasses the per-row picker because it auto-creates accounts.

**Preview step (groups):**

Each row's parse result renders as a collapsible card.

- **Bank-style group** (`kind: "bank"` — checking/savings/debt/other): statement balance + sortable transactions table (date↑↓, amount↑↓). Per-row edit and remove like today's `ImportModal`.
- **Investment-style group** (`kind: "investment"` — brokerage/retirement): statement date + cash + sortable holdings (ticker / market value) + sortable investment transactions (date / amount). Tie-out banner from existing `PortfolioImportModal`.
- Per-group `error` field renders an error stripe with "Remove row & continue."
- Mixed-type warning (non-blocking amber banner) when a checking account picker is paired with a file that parsed as an investment statement, and vice versa.

**Post-save:**

Modal closes. Toast banner at top of Dashboard:

> Saved 47 transactions and 1 snapshot. **12 new transfer candidates** found — [Review now] / Dismiss.

Auto-dismisses after 8 s. `TransferReviewBadge` count updates regardless. "Review now" opens the existing `TransferReviewModal`.

### Backend

Two new endpoints under a new router module `app/imports/statements_router.py`. Old endpoints (`/import/preview`, `/import/file-preview`, `/import/confirm`, `/portfolio/import/statement*`) stay wired for backward compat (Plaid sync, legacy tests).

**`POST /import/statements/preview`** (multipart/form-data)

Form fields:
- `rows`: JSON string — `[{"row_id": "r1", "account_id": "uuid"}, ...]`
- For each `row_id`: zero or more file uploads using that `row_id` as the form-field name.

Per row:
1. Validate `account_id` belongs to `user.id` (else 403).
2. Load account `type` from DB.
3. Extract text from each file (`extract_pdf_text` / `extract_csv_text` / decode for `.txt`); aggregate into one string.
4. Dispatch by type:
   - `brokerage | retirement` → `parse_investment_statement` → investment preview.
   - everything else → `parse_accounts_from_text` + `parse_transactions_from_text` → bank preview. Use the picked account's row to derive `balance` (take the latest dated parsed-account row if multiple, fall back to the account's current balance if parser found none).
5. Catch row-level exceptions; do not fail the whole call. Return `error: "..."` on that group.

Response:

```json
{
  "groups": [
    {
      "row_id": "r1",
      "account_id": "uuid",
      "account_name": "Chase Checking",
      "account_type": "checking",
      "kind": "bank",
      "error": null,
      "preview": {
        "statement_date": "2026-02-29",
        "balance": 12430.55,
        "transactions": [
          {"date": "2026-02-12", "description": "Whole Foods", "amount": -84.20, "category": "food"}
        ]
      }
    },
    {
      "row_id": "r2",
      "account_id": "uuid",
      "account_name": "Fidelity Brokerage",
      "account_type": "brokerage",
      "kind": "investment",
      "error": null,
      "preview": {
        "statement_date": "2026-03-31",
        "cash_value": 1200,
        "holdings": [...],
        "investment_transactions": [...],
        "total_value_reported": 85800,
        "account_hint": "Brokerage ...4567"
      }
    }
  ]
}
```

**`POST /import/statements/confirm`** (JSON)

```json
{
  "groups": [
    {"row_id": "r1", "account_id": "uuid", "kind": "bank",
     "balance": 12430.55, "transactions": [...]},
    {"row_id": "r2", "account_id": "uuid", "kind": "investment",
     "statement_date": "2026-03-31", "cash_value": 1200,
     "holdings": [...], "investment_transactions": [...]}
  ]
}
```

Per group:
- `kind: "bank"` → update `accounts.balance` for `account_id` (with `cache_patch` + `record_history(source="file_import")`); insert each transaction with `account_id` set, `source="manual"`. Skip rows where a `(user_id, source="manual", account_id, date, amount, description)` row already exists. Return `transactions_created`, `transactions_skipped`, `balance_updated`.
- `kind: "investment"` → call existing `snapshots.create_statement_snapshot(...)` (idempotent on `(account_id, snapshot_date)`). Return `snapshot_id`, `holdings_count`, `txns_count`.

After all groups processed, call `safe_scan_transfers_for_user(db, uid)` once and read newly-flagged candidate count (existing query: pending candidates created within the last 60 s for this user).

Response:

```json
{
  "ok": true,
  "saved": [
    {"row_id": "r1", "account_id": "...", "transactions_created": 45, "transactions_skipped": 2, "balance_updated": true},
    {"row_id": "r2", "account_id": "...", "snapshot_id": "...", "holdings_count": 12, "txns_count": 8}
  ],
  "transfer_candidates_added": 12
}
```

**Atomicity:** per-row, not per-batch. One row's failure does not roll back another row's writes. Failed rows surface in `saved[*].error`.

**Ownership / safety:** every `account_id` rechecked at confirm time (defense against a stale preview from another session).

## Implementation Plan

### Step 1 — Backend: new router (`app/imports/statements_router.py`)

- Define Pydantic models:
  - `RowPreviewRequest` (row_id, account_id)
  - `BankPreviewBody`, `InvestmentPreviewBody`, `PreviewGroup`, `PreviewResponse`
  - `BankConfirmBody`, `InvestmentConfirmBody`, `ConfirmGroup`, `ConfirmRequest`, `SavedRow`, `ConfirmResponse`
- Implement `/preview` and `/confirm`. Reuse helpers from existing `app/imports/router.py` (`extract_pdf_text`, `extract_csv_text`, `_account_identity`) and `app/portfolio/router.py` (`_coerce_statement_preview`, `_assert_owns_account`, `snapshots.create_statement_snapshot`). Lift shared helpers into small modules if reuse forces it; otherwise import directly.
- Add a small helper for "count transfer candidates created in the last 60s" (read from `transfer_candidates` where `status='pending'` and `created_at > now() - 60s`).
- Mount router in `app/main.py`.

### Step 2 — Backend tests (`backend/tests/imports/test_statements_router.py`)

Cover:
- Dispatch by type (bank vs investment shape)
- Per-row errors don't fail the whole call
- Confirm writes correct rows + skips dupes on re-run
- Confirm rejects another user's `account_id` (403)
- Confirm calls `safe_scan_transfers_for_user` once and `transfer_candidates_added` matches the count
- Multi-row mixed batch end-to-end

### Step 3 — Frontend: client functions

`frontend/src/lib/imports.ts` (new):
- `previewStatements(rows: {rowId, accountId, files: File[]}[]): Promise<PreviewResponse>`
- `confirmStatements(groups): Promise<ConfirmResponse>`

Shared types match the backend response shapes.

### Step 4 — Frontend: `UnifiedImportModal`

New `frontend/src/components/UnifiedImportModal.tsx`.

Sub-components, top-down:
- `UploadStep` — rows array, `+ Add another account`, Plaid section.
- `RowEditor` — account dropdown (with inline create), file picker (multi).
- `PreviewStep` — groups array → list of `BankPreviewCard` / `InvestmentPreviewCard`.
- `BankPreviewCard` — sortable transactions table; reuses row-edit primitives from current `ImportModal`.
- `InvestmentPreviewCard` — sortable holdings + investment txn tables, tie-out banner; ported from current `PortfolioImportModal`.
- `PostSaveToast` — rendered at Dashboard root via a small context (`ImportToastProvider`) so the toast outlives the closing modal.

Data-testids preserved across rewrites where eval-frontend already references them.

### Step 5 — Repoint entry points

- `pages/Dashboard.tsx` — replace `ImportModal` import + render with `UnifiedImportModal`. Wrap children in `ImportToastProvider`. Wire "Review now" toast action to `setReviewOpen(true)`.
- `components/portfolio/PortfolioPage.tsx` — replace `PortfolioImportModal` with `UnifiedImportModal` (pass `initialAccountId`).
- `components/TransferReviewModal.tsx` — its `onRequestUpload` already opens the Dashboard's import modal via prop; no change required.
- Delete `components/ImportModal.tsx` and `components/portfolio/PortfolioImportModal.tsx`. Delete their tests; replace with new ones.
- `lib/portfolio.ts` — keep `previewStatement` / `previewStatementFile` / `confirmStatementImport` (still used by Plaid path? double-check; remove if dead).

### Step 6 — Frontend tests

`UnifiedImportModal.test.tsx` (vitest + RTL):
- Renders one empty row on open
- `+ Add another account` appends row
- Account dropdown lists existing accounts; `+ New account` inline form posts and selects
- Preview button disabled until valid
- Preview groups render correct shape and respect `data-testid`
- Save calls confirm with edited payload
- Toast appears after save with transfer count + Review-now wiring

Update `eval-frontend` Spec A inventory to reference the new component's testids (handled in the test report run, not in this branch's code).

### Step 7 — Manual smoke

Servers already running. Walk through:
1. Header → unified modal → 1 checking + 1 brokerage upload → preview → save → toast appears → click Review now → modal opens.
2. Portfolio tab → modal → pre-selected account in first row → save → snapshot appears in chart.
3. Empty state → inline-create account → upload → save.

## File-level change list

**Create**
- `backend/app/imports/statements_router.py`
- `backend/tests/imports/test_statements_router.py`
- `frontend/src/lib/imports.ts`
- `frontend/src/components/UnifiedImportModal.tsx`
- `frontend/src/components/ImportToastProvider.tsx`
- `frontend/src/components/__tests__/UnifiedImportModal.test.tsx`

**Modify**
- `backend/app/main.py` — mount new router
- `frontend/src/pages/Dashboard.tsx` — swap modal, add toast provider
- `frontend/src/components/portfolio/PortfolioPage.tsx` — swap modal

**Delete**
- `frontend/src/components/ImportModal.tsx`
- `frontend/src/components/portfolio/PortfolioImportModal.tsx`
- Their existing test files (if any)

## Open risks

- **Tests against deleted modals:** Spec A frontend eval references `ImportModal` testids — those scenarios will fail until the inventory is updated. Acceptable for this branch; eval inventory update is its own follow-up.
- **Toast provider re-render:** rendering at Dashboard root + context bump should not retrigger data fetches. Sanity-check via React DevTools during manual smoke.
- **Account-type mismatch:** parser may legitimately produce holdings from a file the user assigned to a checking account (e.g., a combined Schwab statement). The amber banner is non-blocking; user can still save the bank-shaped data and re-upload to the right account separately.
