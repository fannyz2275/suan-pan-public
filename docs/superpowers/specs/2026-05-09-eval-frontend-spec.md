# Spec A — Frontend Behavior Eval

> Part of the three-spec eval suite: frontend behavior, backend correctness, and chat-advisor quality. See the sibling backend and chat-quality specifications for their contracts.
>
> **Spec A scope:** frontend rendering, interaction, and network call shape only.
> **Spec B** owns backend math correctness, tool output accuracy, and engine invariants.
> **Spec C** owns chat-advisor judgment quality, narration form, and LLM-mediated assertions.

---

## 1. Purpose + Scope

Spec A answers a single question: **does every UI surface render correctly, respond to user interaction, and fire network requests with the right shape?**

Covered:
- Component rendering in happy-path, empty-state, and error-state scenarios
- DOM structure (element presence, text content, ARIA attributes)
- Network request shape: URL pattern, HTTP method, query parameters, request body keys
- User interaction wiring: button clicks advance state, chips filter data, modal steps flow correctly, sort toggles change table order

Not covered by this spec (explicit out-of-scope, see Section 9):
- Whether the numbers the backend returns are mathematically correct (Spec B)
- Whether the advisor's prose is good, mentions the right things, or pushes back appropriately (Spec C)
- Full Plaid sandbox integration (manual smoke test)
- Visual regression beyond a warning-level screenshot diff

---

## 2. Methodology

### Test runner
**Playwright** using the existing config at `frontend/playwright.config.ts`. The config targets Chromium Desktop, runs tests serially (`workers: 1`, `fullyParallel: false`), and sets `baseURL` to `http://localhost:5173`. Test files live under `frontend/e2e/`. Add one `*.spec.ts` file per UI surface (see Section 3).

### DB fixture seeding
Each test run seeds the DB to a known state using the `Seed` API from `backend/tests/evals/shared/seed.py` (already shipped at commit `10297f1`). The typical pattern:

```python
# run before the Playwright process starts (e.g., in a pytest-based setup hook
# or a Node.js globalSetup script that shells out to Python)
from backend.tests.evals.shared.seed import Seed

Seed() \
  .with_user(user_id="u-eval-a") \
  .with_account(id="acc-brok-1", type="brokerage", name="Fidelity", balance=50000) \
  .with_security("AAPL", asset_class="equity", sector="Technology", region="US") \
  .with_security("BND", asset_class="fixed_income", sector=None, region="US") \
  .with_snapshot("acc-brok-1", snapshot_date="2026-04-01",
                 holdings=[
                   {"ticker": "AAPL", "qty": 10, "price": 185.00},
                   {"ticker": "BND",  "qty": 50, "price": 74.50},
                 ]) \
  .with_snapshot("acc-brok-1", snapshot_date="2026-05-01",
                 holdings=[
                   {"ticker": "AAPL", "qty": 10, "price": 190.00},
                   {"ticker": "BND",  "qty": 50, "price": 73.80},
                 ]) \
  .apply(db)
```

Tests authenticate as the seeded user via `TEST_EMAIL`/`TEST_PASSWORD` env vars that correspond to the seeded `user_id`. After each test file the seed is torn down (truncate the eval user's rows) so tests don't bleed state.

**No `POST /eval/seed` endpoint.** Earlier drafts proposed an HTTP endpoint protected by `EVAL_MODE=true`. Adding a write-anything endpoint to production code, even gated, expands the attack surface and risks a config bug deploying with the gate open. Spec A instead has Playwright's `globalSetup` shell out to a Python script:

```ts
// frontend/e2e/global-setup.ts
import { execSync } from 'child_process';
export default async function globalSetup() {
  // 1. Verify backend is in eval mode (refuses to run otherwise — see §6.4)
  const health = await fetch('http://localhost:8000/eval/health').then(r => r.json());
  if (!health.eval_mocks) {
    throw new Error('Backend not in eval mode (set EVAL_MOCKS=1 before starting uvicorn)');
  }

  // 2. Apply the seed via Python (no HTTP needed)
  execSync('python -m backend.tests.evals.shared.seed_runner --fixture single_brokerage', { stdio: 'inherit' });

  // 3. Sanity-check: hit the API as the eval user, assert expected fixture cardinality
  await assertSetupValidation();

  // 4. Login once and persist auth state for all tests (see §5.2)
  await loginAndSaveStorageState();
}
```

This keeps the seed code Python-side (where it lives) and adds zero production code.

### Mocking external services
See Section 6 for the full mocking conventions. In short:

- **Gemini** (statement parser): monkey-patched at the FastAPI route level before the backend process starts.
- **Plaid SDK**: `_plaid_client` on the router replaced with a fake object.
- **FRED**: `fetch_fred_series` patched to return canned `{date: float}` dicts.

### Test file structure
```
frontend/e2e/
  portfolio/
    account-scope-chips.spec.ts
    time-series-chart.spec.ts
    allocation-stacked-bars.spec.ts
    holdings-table.spec.ts
    attribution-waterfall.spec.ts
    attribution-chips.spec.ts
    portfolio-page-buttons.spec.ts
  unified-import-modal.spec.ts
  dashboard-tabs.spec.ts
  chat-table-pill.spec.ts
```

---

## 3. Surface Inventory

> **How to read this table:**
> - "Happy path" — normal state with seeded data present.
> - "Empty state" — seeded user has no relevant data (no holdings, no snapshots, etc.).
> - "Error state" — backend returns a non-2xx or the network is dropped (intercept via `page.route`).
> - "Key DOM assertions" — `data-testid` selectors where specified; otherwise describe the role/text pattern.
> - "Key network assertion" — use `page.waitForRequest(req => ...)` to capture; assert URL path + method + params.

### 3.1 `AccountScopeChips`

| Field | Detail |
|---|---|
| **Component** | `frontend/src/components/portfolio/AccountScopeChips.tsx` |
| **Happy path** | "All investments" chip renders active (dark background); one chip per brokerage/retirement account from seeded fixture renders beside it. |
| **Empty state** | No brokerage/retirement accounts seeded — only "All investments" chip appears; no per-account chips. |
| **Error state** | `GET /finance/accounts` returns 500 — chip row still renders "All investments" chip; no crash. |
| **Key DOM assertions** | `data-testid="scope-chip-all"` is present and has `aria-pressed="true"` (or Tailwind active class). `data-testid="scope-chip-{account_id}"` exists for each seeded account. |
| **Key network assertion** | `await page.waitForRequest(req => req.url().includes('/finance/accounts') && req.method() === 'GET')` fires on PortfolioPage mount. |

**Interaction test:** click a per-account chip, assert `data-testid="scope-chip-{id}"` gains the active class and "All investments" chip loses it. Subsequent chart/table fetches must include `account_id={id}` in query params.

---

### 3.2 `PortfolioTimeSeriesChart`

| Field | Detail |
|---|---|
| **Component** | `frontend/src/components/portfolio/PortfolioTimeSeriesChart.tsx` |
| **Happy path** | Chart renders with a `<recharts>` SVG (or its container `data-testid="timeseries-chart"`) visible; the "Portfolio value" heading is present; at least one `<path>` for the portfolio line exists inside the SVG. |
| **Empty state** | API returns `{series: [], overlays: []}` — "No snapshots in this window" message renders; SVG container may still be present but the path count is 0. |
| **Error state** | `GET /portfolio/timeseries` returns 500 — chart area shows no paths; no uncaught JS exception in console (assert via `page.on('console', ...)`). |
| **Key DOM assertions** | `data-testid="timeseries-chart"` wraps the ResponsiveContainer. Window buttons (1M, 3M, 6M, YTD, 1Y, All) are each a `<button>` with visible text. Overlay chips (10Y, CPI, SPY) are each a `<button>`. |
| **Key network assertion** | `page.waitForRequest(req => req.url().includes('/portfolio/timeseries') && req.url().includes('from_date=') && req.url().includes('to_date='))` |

**Interaction tests:**
1. Click "1M" window button — assert new `GET /portfolio/timeseries` fires with `from_date` within 31 days of today.
2. Click "10Y" overlay chip — assert subsequent `GET /portfolio/timeseries` includes `overlays=10y` in query string; right-axis `<YAxis>` renders (second `yAxisId`).
3. Toggle "CPI" after "10Y" is active — assert `overlays=10y,cpi` (order-agnostic) in the next request.

---

### 3.3 `AllocationStackedBars`

| Field | Detail |
|---|---|
| **Component** | `frontend/src/components/portfolio/AllocationStackedBars.tsx` |
| **Happy path** | Three labeled bars render: "ASSET CLASS", "SECTOR", "REGION" (uppercase tracking labels). Each bar has at least one colored segment. "Allocation" heading present. |
| **Empty state** | All three exposure dimensions return `[]` — component returns `null`; no "Allocation" heading or bar container in DOM. Assert `page.locator('[data-testid="allocation-bars"]').count()` equals 0. |
| **Error state** | Any `/portfolio/exposure` call returns 500 — component renders null (same as empty, since state stays at `[]` on error); no crash. |
| **Key DOM assertions** | `data-testid="allocation-bars"` on the outer container. Each bar row: `data-testid="bar-asset_class"`, `data-testid="bar-sector"`, `data-testid="bar-region"`. Each segment has a `title` attribute matching `"{label}: {percent}%"` pattern. |
| **Key network assertion** | Three parallel fetches: `GET /portfolio/exposure?dim=asset_class`, `GET /portfolio/exposure?dim=sector`, `GET /portfolio/exposure?dim=region`. Assert all three fire on mount. |

**Interaction test (filter wiring):** Click a segment in the "SECTOR" bar. Assert `data-testid="bar-sector"` has the clicked segment at full opacity and the others at reduced opacity (`opacity: 0.4` in inline style). Assert a `HoldingsTable`-related fetch fires with the appropriate filter parameter if the `onSelect` callback is wired from `PortfolioPage` — or assert the prop `onSelect` was called (via a Playwright evaluate or by observing the URL state). Note: current `PortfolioPage.tsx` passes `onSelect` to `AllocationStackedBars` but `HoldingsTable` does not yet accept a filter prop — flag this as a testability gap (see Section 13).

---

### 3.4 `HoldingsTable`

| Field | Detail |
|---|---|
| **Component** | `frontend/src/components/portfolio/HoldingsTable.tsx` |
| **Happy path** | Table renders with "Holdings" heading. Seeded holdings (e.g., AAPL, BND) appear as rows. Default sort is by `market_value` descending (higher-value holding is row 1). |
| **Empty state** | API returns `[]` — "No holdings yet." message renders in a `<td colSpan={4}>`. |
| **Error state** | `GET /portfolio/holdings` returns 500 — table renders with "No holdings yet." message (state stays `[]`); no crash. |
| **Key DOM assertions** | `data-testid="holdings-table"` on the table wrapper. Column headers: `data-testid="col-ticker"`, `data-testid="col-quantity"`, `data-testid="col-market-value"`, `data-testid="col-percent"`. Each row: `data-testid="holding-row-{ticker}"`. |
| **Key network assertion** | `GET /portfolio/holdings` (no `account_id` param when "All investments" is selected; includes `account_id=acc-brok-1` when account chip is active). |

**Interaction tests:**
1. Click "Ticker" column header — rows reorder alphabetically ascending; arrow indicator `▲` appears next to "Ticker".
2. Click "Ticker" again — rows reorder descending; indicator flips to `▼`.
3. Click "Market value" header — reverts to market-value descending (default); AAPL row appears above BND if AAPL has higher value.
4. With "All investments" active, click account scope chip for `acc-brok-1` — `GET /portfolio/holdings?account_id=acc-brok-1` fires.

---

### 3.5 `AttributionWaterfall`

| Field | Detail |
|---|---|
| **Component** | `frontend/src/components/portfolio/AttributionWaterfall.tsx` |
| **Happy path** | "Attribution" heading and the period summary line render. Recharts `BarChart` SVG is present with multiple bar segments (Start, Market, Contributions, Withdrawals, Dividends, Trades, End). |
| **Empty state / no data** | API returns a non-2xx or throws — component returns `null`; no "Attribution" heading in DOM. |
| **Error state** | Same as empty: `fetchAttribution` catches the error and sets `data = null`; component renders nothing. |
| **Key DOM assertions** | `data-testid="attribution-waterfall"` on the outer `<div>`. `data-testid="attribution-heading"` on the `<h3>`. `data-testid="unattributed-banner"` on the amber warning `<div>` — present only when `Math.abs(data.unattributed) >= 1`. |
| **Key network assertion** | `GET /portfolio/attribution?from_date={from}&to_date={to}` fires on mount. Include `account_id` when scoped. |

**Interaction test (unattributed banner):** Seed a snapshot pair where `unattributed` would be non-zero (e.g., snapshot total differs from start + flows). Assert `data-testid="unattributed-banner"` is visible and contains the text "unattributed". Seed a clean pair — assert banner is absent.

**Amber color check (warning-level only):** The banner `<div>` should have `bg-amber-50` class. Assert via `page.locator('[data-testid="unattributed-banner"]').evaluate(el => el.classList.contains('bg-amber-50'))`. Mark as `[A11Y]` tag level, not a failure gate.

---

### 3.6 `AttributionChips`

| Field | Detail |
|---|---|
| **Component** | `frontend/src/components/portfolio/AttributionChips.tsx` |
| **Context** | This component is rendered inside `ChatPanel` (not `PortfolioPage`) when a chat turn's SSE stream emits a `tool_result` event with `tool_name === "portfolio_get_attribution"`. It is absent when no such tool result is present. |
| **Happy path** | Simulate a chat turn where the mocked advisor stream emits a `portfolio_get_attribution` tool result with non-trivial bucket values (all `>= 100`). Assert `data-testid="attribution-chips"` renders above the assistant message prose. Assert at least one chip is visible with green or red color class. |
| **Absent state** | Chat turn does not emit a `portfolio_get_attribution` result — `data-testid="attribution-chips"` does not appear. |
| **Error state** | Stream emits a malformed JSON tool result — component does not render; no crash. |
| **Key DOM assertions** | `data-testid="attribution-chips"` on the `<div class="space-y-2 mb-2">` wrapper. Each chip: role is `generic` (a `<span>`); color class is `bg-green-50` or `bg-red-50`. Period summary line `data-testid="attribution-chips-period"` shows `from_date → to_date`. |
| **Key network assertion** | The SSE stream endpoint `POST /advisor/chat` fires; test intercepts the mocked SSE response (the backend is mocked to return a canned SSE payload containing the tool result). |

**Note for test author:** Rather than driving a full chat interaction through SSE, inject the `attributionByMessageId` state into the component tree via Playwright evaluate, or render `AttributionChips` directly with a `data` prop fixture in a lightweight component-level test. Full SSE wiring is covered in Spec C.

---

### 3.7 `UnifiedImportModal` — multi-row upload + per-account preview

| Field | Detail |
|---|---|
| **Component** | `frontend/src/components/UnifiedImportModal.tsx` (and `ImportToastProvider.tsx`) |
| **Happy path (single row)** | Modal is open, dropdown shows seeded accounts plus `+ New account…`. Pick an account, attach a file via the hidden `<input data-testid="unified-row-files">`, click `Preview` → `POST /import/statements/preview` (multipart, fields `rows` + `<rowId>` per file). Preview cards render. Click `Save all` → `POST /import/statements/confirm`. Toast appears with summary + transfer count. |
| **Multi-row** | Click `+ Add another account` → second `[data-testid="unified-row"]` appears (cap at 10). Each row gets its own account picker and file picker; one Preview request includes both rows; the response contains two `groups`. |
| **Inline account creation** | Selecting `+ New account…` option reveals `data-testid="unified-new-name"` + `data-testid="unified-new-type"` + `data-testid="unified-new-save"`. Clicking Create calls `POST /finance/accounts` and auto-selects the newly created account on that row. |
| **Bank-style preview card** | When the row's account type is `checking`/`savings`/`debt`/etc., the preview card shows balance input (`data-testid="bank-balance"`), a transactions table, and a sort dropdown (`data-testid="bank-txn-sort"`) supporting date / amount sort orders. |
| **Investment-style preview card** | When the row's account type is `brokerage`/`retirement`, the card shows cash/holdings/statement-date cells, a holdings table with `data-testid="inv-holdings-sort"` (ticker / market-value), and an investment-transactions table with `data-testid="inv-txn-sort"`. |
| **Tie-out match state** | Investment preview where `total_value_reported` equals `cash_value + sum(holdings.market_value)` within 1% (or $1) tolerance — assert `data-testid="tie-out-match"` is visible and contains "matches". |
| **Tie-out mismatch state** | Investment preview where `total_value_reported` differs beyond tolerance — assert `data-testid="tie-out-banner"` is visible and contains "Tie-out mismatch". |
| **Per-row error** | Mock `POST /import/statements/preview` returns one group with `error: "Could not parse"`. Assert the matching `data-testid="preview-card"` renders the error string and Save button is still enabled (other groups can save). |
| **Error state (parse)** | `POST /import/statements/preview` returns 422 globally — error message renders in red below the rows; modal stays on the upload step. |
| **Empty rows** | No file or no account selected — `data-testid="unified-preview-btn"` shows `Preview (0 rows)` and is disabled. |
| **Post-save toast** | After `Save all`, mock returns `transfer_candidates_added: N`. Assert `data-testid="import-toast"` is visible; if N > 0, `data-testid="import-toast-review"` is clickable and clicking it opens `TransferReviewModal`. |
| **Key DOM assertions** | `data-testid="unified-import-modal"` on the modal container. `data-testid="unified-row"` on each upload row. `data-testid="unified-row-account"` on the account `<select>`. `data-testid="unified-row-files"` on the hidden file input. `data-testid="unified-add-row"` on the add-row button. `data-testid="unified-row-remove"` on each row's × button. `data-testid="unified-preview-btn"` and `data-testid="unified-save-btn"` on footer buttons. `data-testid="preview-card"` on each per-account preview. `data-testid="preview-card-remove"` on the per-card Remove link. `data-testid="tie-out-banner"` / `data-testid="tie-out-match"` on investment-card tie-out elements. `data-testid="import-toast"` / `data-testid="import-toast-review"` on the post-save toast. |
| **Key network assertions** | Preview: `POST /import/statements/preview` is `multipart/form-data` with form field `rows` (JSON-encoded `[{row_id, account_id}, ...]`) and one file form-field per `row_id`. Confirm: `POST /import/statements/confirm` body is `{ groups: [{row_id, account_id, kind: "bank" \| "investment", ...payload}] }`. Inline account create: `POST /finance/accounts` body has `{name, type, balance: 0}`. |

**Step flow test sequence:**
```
open modal (header or Portfolio tab)
→ pick account in row 1 → setInputFiles on unified-row-files
→ click unified-preview-btn
→ waitForRequest POST /import/statements/preview (multipart)
→ verify preview-card[count=1] visible
→ click unified-save-btn
→ waitForRequest POST /import/statements/confirm
→ verify modal closes + import-toast visible
```

**Back button test:** On preview step, click "← Back" — the upload rows reappear with their saved state intact.

---

### 3.8 "Import accounts" / "Import statement" Buttons — modal entry points

| Field | Detail |
|---|---|
| **Context** | Three entry points open the same `UnifiedImportModal`: the header `+ Import accounts` button (Dashboard), the Portfolio tab `Import statement` button (`PortfolioPage.tsx`), and the "Upload" action inside `TransferReviewModal`. |
| **Happy path** | Each button is visible; click opens `[data-testid="unified-import-modal"]`. Portfolio tab passes the currently-scoped account as `initialAccountId` so row 1 is pre-selected. |
| **Key DOM assertions** | `data-testid="btn-import-statement"` on the Portfolio button (text is "Import statement"). The header button is the `<button>` containing "+ Import accounts". |
| **Key network assertion** | No network call fires on button click itself; the modal triggers requests when the user clicks Preview / Save. |

---

### 3.9 "Sync Plaid" Button on `PortfolioPage`

| Field | Detail |
|---|---|
| **Context** | `PortfolioPage.tsx` renders a light "Sync Plaid" `<button>`. On click it calls `syncPlaidInvestments()` which hits `POST /portfolio/sync/plaid`. |
| **Happy path** | Button is visible and enabled; click fires `POST /portfolio/sync/plaid`; after response, success message "Synced — N snapshot(s) written" appears in the `<span>` beside the button. `refreshKey` is bumped (observable as a new `GET /portfolio/timeseries` request firing). |
| **Error state** | `POST /portfolio/sync/plaid` returns 500 — "Sync failed — check Plaid connection" message appears; button re-enables. |
| **Disabled state** | During the in-flight request, button shows "Syncing…" text and is `disabled`. |
| **Key DOM assertions** | `data-testid="btn-sync-plaid"` on the button. `data-testid="sync-status-msg"` on the status `<span>`. |
| **Key network assertion** | `await page.waitForRequest(req => req.url().includes('/portfolio/sync/plaid') && req.method() === 'POST')` fires within 2s of click. |

---

### 3.10 Dashboard "Portfolio" Tab

| Field | Detail |
|---|---|
| **Context** | `Dashboard.tsx` renders a tab bar with "Overview", "Accounts", "Portfolio", "Cash Flow". |
| **Happy path** | "Portfolio" tab button is visible; click sets `activeTab` to `'portfolio'`; `PortfolioPage` component mounts (assert `data-testid="portfolio-page"` or presence of `data-testid="btn-import-statement"`). |
| **Active state styling** | Active tab has `border-primary text-primary` classes; inactive tabs have `border-transparent text-muted-foreground`. Assert the Portfolio tab has `border-b-2 border-primary` after click. |
| **Key DOM assertions** | Each tab button: `data-testid="tab-overview"`, `data-testid="tab-accounts"`, `data-testid="tab-portfolio"`, `data-testid="tab-cashflow"`. |
| **Key network assertion** | When Portfolio tab is clicked, `GET /finance/accounts` fires (from `AccountScopeChips` mount). |

---

### 3.11 `TablePill` (chat-side inline table)

| Field | Detail |
|---|---|
| **Component** | `frontend/src/components/TablePill.tsx` |
| **Coverage level** | Light — this is an existing component. Test happy path + collapsed/expanded toggle only. |
| **Happy path** | `TablePill` renders with a collapsed header showing `table.title` and `table.summary`. Click the header expands the panel (assert `aria-expanded="true"`). Table rows render. Footer shows row count. |
| **Empty rows** | `table.rows = []` — header renders, expand shows an empty `<tbody>`. |
| **Large table** | `table.rows.length > 100` — "Open full view →" button appears in footer. |
| **Key DOM assertions** | `data-testid="table-pill"` on the outer container. `data-testid="table-pill-toggle"` on the toggle `<button>`. `aria-expanded` attribute on the toggle button. `data-testid="table-pill-body"` on the expanded content section. |
| **Key network assertion** | None — `TablePill` is purely presentational; data is passed via props. |

---

## 4. Assertion Library

Use these patterns consistently across all spec files. Do not mix patterns for the same assertion type.

### 4.1 DOM presence
```typescript
// Element exists and is visible
await expect(page.locator('[data-testid="attribution-waterfall"]')).toBeVisible();

// Element is absent from DOM
await expect(page.locator('[data-testid="allocation-bars"]')).toHaveCount(0);
```

### 4.2 Text content
```typescript
// Exact text
await expect(page.locator('h3:has-text("Allocation")')).toBeVisible();

// Contains substring (prefer toContainText over regex for readability)
await expect(page.locator('[data-testid="sync-status-msg"]')).toContainText('snapshot');

// Do NOT assert on full text with whitespace (brittle — see Section 12)
```

### 4.3 Network call shape
```typescript
// Capture and assert URL structure
const req = await page.waitForRequest(
  req => req.url().includes('/portfolio/timeseries') && req.method() === 'GET'
);
expect(new URL(req.url()).searchParams.get('from_date')).toBeTruthy();
expect(new URL(req.url()).searchParams.get('overlays')).toContain('10y');

// Assert POST body keys (not full body — too brittle)
const req = await page.waitForRequest(
  req => req.url().includes('/portfolio/import/statement/confirm') && req.method() === 'POST'
);
const body = req.postDataJSON();
expect(body).toHaveProperty('account_id');
expect(body).toHaveProperty('holdings');
expect(Array.isArray(body.holdings)).toBe(true);
```

### 4.4 Mock a network response (intercept)
```typescript
await page.route('**/portfolio/import/statement', async route => {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(CANNED_STATEMENT_PREVIEW),
  });
});
```

### 4.5 Screenshot diff (warning-level only, not a failure gate)
```typescript
// Attach as a soft assertion; never use toMatchSnapshot() in CI gates
await page.screenshot({ path: 'e2e/screenshots/attribution-waterfall.png' });
// Compare manually or attach to the run report; do NOT call expect(page).toMatchSnapshot()
```

### 4.6 Accessibility (axe-core, warning-level only)
```typescript
import AxeBuilder from '@axe-core/playwright';

const results = await new AxeBuilder({ page }).analyze();
// Surface violations in the report but do NOT fail the test
if (results.violations.length > 0) {
  console.warn('[A11Y]', JSON.stringify(results.violations, null, 2));
}
```

### 4.7 Class/style assertion
```typescript
// Assert Tailwind class presence (use for active-state chips, tab borders)
await expect(page.locator('[data-testid="scope-chip-all"]'))
  .toHaveClass(/bg-gray-900/);

// Assert inline style (opacity for allocation bar segments)
const opacity = await page.locator('[data-testid="bar-sector"] > div').first()
  .evaluate(el => (el as HTMLElement).style.opacity);
expect(opacity).toBe('0.4');
```

### 4.8 Waiting — always use waitFor, never sleep
```typescript
// Wait for element to appear after async fetch
await page.waitForSelector('[data-testid="holdings-table"]');

// Wait for navigation or URL change
await page.waitForURL(/dashboard/);

// Wait for request — use before triggering the action
const reqPromise = page.waitForRequest(req => req.url().includes('/portfolio/sync/plaid'));
await page.click('[data-testid="btn-sync-plaid"]');
const req = await reqPromise;
```

---

## 5. Fixture Seeding

### Reference fixture: single brokerage account + 2 holdings + 1 snapshot

This is the baseline fixture used in most happy-path tests. Assign it a stable id so test files can reference it by name.

```python
# backend/tests/evals/shared/seed.py  (T4 — to be authored)
FIXTURE_SINGLE_BROKERAGE = (
    Seed()
    .with_user(user_id="u-eval-a", email="eval-a@test.local", password="eval-a-pw")
    .with_account(
        id="acc-brok-1",
        type="brokerage",
        name="Fidelity Brokerage",
        balance=50000,
        user_id="u-eval-a",
    )
    .with_security("AAPL", asset_class="equity", sector="Technology", region="US")
    .with_security("BND",  asset_class="fixed_income", sector=None, region="US")
    .with_snapshot(
        account_id="acc-brok-1",
        snapshot_date="2026-04-01",
        cash_value=5000,
        holdings=[
            {"ticker": "AAPL", "qty": 10, "price": 185.00, "cost_basis": 150.00},
            {"ticker": "BND",  "qty": 50, "price": 74.50,  "cost_basis": 74.00},
        ],
        total_value_reported=12975.00,
    )
    .with_snapshot(
        account_id="acc-brok-1",
        snapshot_date="2026-05-01",
        cash_value=5100,
        holdings=[
            {"ticker": "AAPL", "qty": 10, "price": 190.00, "cost_basis": 150.00},
            {"ticker": "BND",  "qty": 50, "price": 73.80,  "cost_basis": 74.00},
        ],
        total_value_reported=13090.00,
    )
)
```

Playwright tests load this fixture by calling the seed's `apply(db)` in a `globalSetup` script that runs before the first test, then `teardown(db)` in `globalTeardown`. Alternatively, each `*.spec.ts` file can call a thin HTTP endpoint `POST /eval/seed` (protected behind a `EVAL_MODE=true` env var) that triggers the seed server-side.

### Fixture for empty-state tests

```python
FIXTURE_NO_HOLDINGS = (
    Seed()
    .with_user(user_id="u-eval-empty", email="eval-empty@test.local", password="eval-empty-pw")
    .with_account(id="acc-brok-2", type="brokerage", name="Empty Brokerage", balance=0, user_id="u-eval-empty")
    # No snapshots, no holdings
)
```

---

## 6. Mocking External Services

All mocks are applied before the backend process starts. The recommended approach is to set env vars or a fixtures-mode flag (`EVAL_MOCKS=1`) that the FastAPI app reads at startup to swap real clients for fakes.

### 6.1 Gemini — statement parser

**What to mock:** `app.portfolio.statement_parser.parse_investment_statement`

**How:** Monkey-patch at the FastAPI app level in a pytest `conftest.py` or in a dedicated backend startup script used only in eval mode.

```python
# backend/tests/evals/frontend/conftest.py  (or globalSetup script)
from unittest.mock import patch, AsyncMock
from app.portfolio import statement_parser

CANNED_STATEMENT_PREVIEW = {
    "statement_date": "2026-04-30",
    "cash_value": 5000.00,
    "account_hint": "FIDELITY BROKERAGE ****1234",
    "total_value_reported": 12975.00,
    "holdings": [
        {"ticker": "AAPL", "name": "Apple Inc.", "quantity": 10, "price": 185.00,
         "market_value": 1850.00, "cost_basis": 1500.00},
        {"ticker": "BND",  "name": "Vanguard Total Bond", "quantity": 50, "price": 74.50,
         "market_value": 3725.00, "cost_basis": 3700.00},
    ],
    "investment_transactions": [],
}

patcher = patch.object(statement_parser, 'parse_investment_statement',
                       new=AsyncMock(return_value=CANNED_STATEMENT_PREVIEW))
patcher.start()
```

The frontend spec only exercises the UI flow (input → preview → confirm). The actual Gemini parsing accuracy is Spec B territory. The mock ensures the preview step always renders the same data regardless of Gemini availability.

**Alternative:** When the test intercepts at the Playwright layer (see Section 4.4), route `**/portfolio/import/statement` to return `CANNED_STATEMENT_PREVIEW` directly. This avoids backend startup complexity but means the `POST /portfolio/import/statement/confirm` call goes to the real backend — which is fine for Spec A since we only care about the UI flow.

### 6.2 Plaid SDK

**What to mock:** `app.plaid.router._plaid_client`

**How:** Replace with a fake object whose methods return canned responses.

```python
class FakePlaidClient:
    async def investments_holdings_get(self, req):
        return FakeResponse(
            accounts=[FakeAccount(account_id="acc-brok-1", balances=FakeBalances(current=50000))],
            holdings=[],
            securities=[],
        )
    async def investments_transactions_get(self, req):
        return FakeResponse(investment_transactions=[], securities=[])

# Apply before test run:
import app.plaid.router as plaid_router
plaid_router._plaid_client = FakePlaidClient()
```

The "Sync Plaid" test in Spec A only verifies that clicking the button fires `POST /portfolio/sync/plaid`, the status message appears, and `refreshKey` bumps (observable as a new chart request). It does not verify that Plaid data is correctly transformed — that's Spec B.

For the mocked response, the `FakePlaidClient.investments_holdings_get` should return at least one holding so the sync result shows `snapshots_written: 1`.

### 6.3 FRED

**What to mock:** `app.portfolio.fred.fetch_fred_series`

### 6.4 EVAL_MOCKS validation gate

The backend MUST refuse external calls if `EVAL_MOCKS=1` is unset when the eval suite runs. Without this gate, a developer who forgets the env var will hit production Gemini/Plaid/FRED — costing real API spend and producing tests that pass for the wrong reason.

**Backend exposes a `/eval/health` endpoint** (gated by `EVAL_MOCKS=1`; returns 404 in production):

```python
# backend/app/main.py — add only when EVAL_MOCKS=1
@app.get("/eval/health")
async def eval_health():
    return {
        "eval_mocks": True,
        "fred_mocked": fred_module.fetch_fred_series.__module__.startswith("unittest"),
        "gemini_mocked": isinstance(statement_parser.parse_investment_statement, AsyncMock),
        "plaid_mocked": isinstance(plaid_router._plaid_client, FakePlaidClient),
    }
```

**Playwright `globalSetup` calls this before the first test runs.** If any mock is inactive, refuse to run with a clear error message — don't let the suite proceed and silently spend money.

**Testability gap (added to §13):** the backend needs the `/eval/health` endpoint and the `EVAL_MOCKS=1` env var read at startup to register it.

**How:**

```python
from unittest.mock import patch
import app.portfolio.fred as fred_module

CANNED_FRED = {
    "DGS10": {"2026-04-01": 4.25, "2026-05-01": 4.18},
    "CPIAUCSL": {"2026-04-01": 312.5, "2026-05-01": 313.1},
}

patcher = patch.object(fred_module, 'fetch_fred_series',
                       side_effect=lambda series_id, *a, **kw: CANNED_FRED.get(series_id, {}))
patcher.start()
```

The FRED mock ensures overlay chip tests (`10Y`, `CPI`) always have data to render without requiring FRED API credentials or network access.

---

## 7. Run Command + Expected Output

### Prerequisites
```bash
# Terminal 1 — start backend with eval mocks enabled
cd backend
EVAL_MOCKS=1 TEST_DB_URL=postgresql://... uvicorn app.main:app --port 8000

# Terminal 2 — start frontend dev server
cd frontend
npm run dev

# Terminal 3 — seed the DB (run once before tests)
python -m backend.tests.evals.shared.seed_runner --fixture single_brokerage

# Terminal 4 — run the Playwright suite
cd frontend
TEST_EMAIL=eval-a@test.local TEST_PASSWORD=eval-a-pw \
  PLAYWRIGHT_BASE=http://localhost:5173 \
  npx playwright test e2e/portfolio/ e2e/dashboard-tabs.spec.ts e2e/chat-table-pill.spec.ts
```

### Sample passing run output
```
Running 34 tests using 1 worker

  ✓  [chromium] › portfolio/account-scope-chips.spec.ts:12:3 › happy path renders all chip + per-account chips (1.2s)
  ✓  [chromium] › portfolio/account-scope-chips.spec.ts:29:3 › empty state: no brokerage accounts (0.8s)
  ✓  [chromium] › portfolio/account-scope-chips.spec.ts:38:3 › click account chip scopes subsequent requests (1.5s)
  ✓  [chromium] › portfolio/time-series-chart.spec.ts:11:3 › happy path chart renders (2.1s)
  ✓  [chromium] › portfolio/time-series-chart.spec.ts:25:3 › 1M window button fires scoped request (1.3s)
  ✓  [chromium] › portfolio/time-series-chart.spec.ts:38:3 › 10Y overlay chip adds overlays param (1.6s)
  ...
  ✓  [chromium] › dashboard-tabs.spec.ts:9:3 › Portfolio tab click mounts PortfolioPage (1.1s)

  34 passed (62s)
```

### Sample failing run output
```
Running 34 tests using 1 worker

  ✓  ...
  ✗  [chromium] › portfolio/attribution-waterfall.spec.ts:44:3 › unattributed banner shows when present (2.3s)

    Error: Timed out 5000ms waiting for [data-testid="unattributed-banner"] to be visible
    Call log:
      - waiting for locator('[data-testid="unattributed-banner"]')
        54 |   await page.click('[data-testid="tab-portfolio"]');
        55 |   await page.waitForSelector('[data-testid="attribution-waterfall"]');
      > 56 |   await expect(page.locator('[data-testid="unattributed-banner"]')).toBeVisible();

    [DOM-MISSING] data-testid="unattributed-banner" — either the testid is missing from AttributionWaterfall.tsx,
    or the seeded snapshots produced unattributed = 0 (check fixture).

  34 tests: 33 passed, 1 failed (65s)
```

Each failure line in the report includes the applicable failure-mode tag from Section 10 (injected by a custom Playwright reporter or by convention in the test's error message string).

---

## 8. Coverage Acceptance Criteria

1. **Surface coverage:** every component listed in Section 3 (AccountScopeChips, PortfolioTimeSeriesChart, AllocationStackedBars, HoldingsTable, AttributionWaterfall, AttributionChips, UnifiedImportModal, Import button, Sync Plaid button, Dashboard Portfolio tab, TablePill) has at minimum one happy-path test and one empty-state test before any portfolio-related PR can merge.

2. **Error state:** every surface that makes a network call has at minimum one error-state test (intercept the relevant route to return 500; assert no crash and a graceful UI state).

3. **New components:** any new component added under `frontend/src/components/portfolio/` requires happy-path + empty-state tests as part of the PR that introduces the component. The PR checklist should include "Spec A tests added for new component."

4. **CI gating:** the Playwright suite runs as a required CI check on every PR targeting `main`. Failures block merge. The suite must complete in under 90 seconds total (current baseline: ~62s for 34 tests). If a new surface pushes total time over 90s, **DO NOT** simply switch to `workers: 2` — the shared seeded DB will produce `[STATE-LEAK]` failures (one worker's teardown nukes another worker's state mid-run). Instead, choose one of:
   - **(preferred)** keep `workers: 1` and split slow tests into a separate non-blocking CI job (e.g., a `slow.spec.ts` glob that runs nightly, not on PRs).
   - **(if parallelism is essential)** provision per-worker users (`u-eval-a-w0`, `u-eval-a-w1`) and route the seed via `process.env.TEST_PARALLEL_INDEX`. Each worker gets its own user, its own seeded data, and its own teardown — no shared state, no collisions.

   Document the chosen approach in the test config; do not let the workers-vs-state collision discovery happen via flakes in CI.

5. **Flake rate:** if a test is tagged `[FLAKY]` in two or more consecutive runs, it must be diagnosed and fixed before the next release. Do not add `retries: 2` to mask flakes.

6. **Phased rollout (Phase 1 → Phase 2).** Spec A is large (11 surfaces × 3 states + interactions = ~50 tests) plus harness + 11 testability-gap PRs. Do **not** attempt to land all of it in one PR.

   - **Phase 1 (must pass first):** `globalSetup` + `seed_runner` + `/eval/health` validation gate + meta-tests from §14 + ONE end-to-end surface chosen for natural selectors (recommend `Dashboard tabs` — already has stable text/role-based selectors, no `data-testid` PRs needed). Verifies the harness end-to-end before scaling.
   - **Phase 2:** remaining 10 surfaces, each gated by its own `data-testid` PR per §13.
   - **Phase 3:** interaction tests + cross-component flows + a11y warnings.

   Phase 2 surfaces can be parallelized across multiple PRs (each a single surface + its testid additions); Phase 1 is the single sequential gate.

---

## 9. Out of Scope

The following are explicitly excluded from Spec A. Asserting on these items in Spec A tests is an anti-pattern that should be caught in code review.

- **LLM judgment quality** — whether the advisor called the right tool, gave good advice, pushed back appropriately. (Spec C)
- **Math correctness** — whether `attribution.market + attribution.contributions + ... = end_value`. (Spec B)
- **Chat narration quality** — whether the advisor's prose is clear, concise, or follows the one-sentence-per-bucket form. (Spec C)
- **Full Plaid sandbox integration** — running the Plaid Link flow end-to-end in a sandbox environment. (Manual smoke test, not eval)
- **Visual regression as a failure gate** — screenshot diffs are attached to run reports as informational artifacts but never cause a test failure. (Warning level only)
- **Backend schema validation** — whether API responses round-trip through their Pydantic schemas correctly. (Spec B)
- **Differential MCP↔REST testing** — whether `portfolio_get_holdings` MCP tool and `GET /portfolio/holdings` return identical data. (Spec B)

---

## 10. Failure-Mode Tags

Every test failure is annotated with one or more of these tags. The annotation lives in the test's `expect` error message or in the custom reporter's output. Aggregate tag frequencies (not just pass rates) are reported per run.

| Tag | Meaning | Severity |
|---|---|---|
| `[DOM-MISSING]` | Expected element did not render — `toBeVisible()` timed out or `toHaveCount(0)` on expected element. Most often means a `data-testid` was never added, or a conditional render gate isn't releasing. | Failure |
| `[DOM-DRIFT]` | Element rendered but its text content or structure differs from what the test expected. Usually caused by a copy change or a structural refactor that moved an element. | Failure |
| `[NETWORK-SHAPE]` | Outbound request URL, method, or body doesn't match the expected shape. Symptom of an API contract change not reflected in the frontend. | Failure |
| `[STATE-LEAK]` | Test state from a prior test polluted the DB or frontend state for this test. Observable as "stale data from another fixture showing up." Always indicates a missing teardown step. | Failure |
| `[A11Y]` | Axe-core accessibility violation. Reported as a warning; does not block CI. Accumulation of `[A11Y]` findings should trigger a dedicated accessibility pass. | Warning |
| `[FLAKY]` | Test passed on retry but failed on initial run. Do not suppress; surface the flake rate as a metric. A flake rate > 5% in a single test is a red flag requiring investigation before the next release. | Warning (tracks flake rate) |

---

## 11. Versioning + Reproducibility

Every test run emits a header block at the top of the report (JSON or text format):

```
Spec A — Frontend Behavior Eval
Run date:        2026-05-09T14:32:00Z
Playwright:      1.44.0
Browser:         Chromium 124.0.6367.78
Fixture version: FIXTURE_SINGLE_BROKERAGE@v1 (from Seed API)
Suan-Pan SHA:    47b62a0
EVAL_MOCKS:      enabled
Backend URL:     http://localhost:8000
Frontend URL:    http://localhost:5173
```

The `Suan-Pan SHA` is `git rev-parse HEAD` at run time. The fixture version is emitted by the `Seed` API (`seed.version()` returns the hash of the fixture definition). Two runs are comparable only if all six fields match.

Store run reports under `docs/test-reports/eval-a-{date}-{sha}.json`. Do not delete old reports; they are the trend dataset.

---

## 12. Anti-Patterns

Do not do any of the following in Spec A tests:

1. **Assert on full HTML strings.** `expect(await page.content()).toContain(...)` is brittle to whitespace, attribute order, and class changes. Use `page.locator` + `toBeVisible` / `toContainText` instead.

2. **Use `sleep()` / `page.waitForTimeout()`.** Always use `page.waitForSelector`, `page.waitForRequest`, or `page.waitForResponse`. Hard-coded sleeps cause both false passes (network was fast) and false failures (network was slow).

3. **Mock the component under test.** If testing `HoldingsTable`, do not mock `HoldingsTable` itself. Mock its dependency (`fetchHoldings` / the network route). The goal is to test the real component with a controlled dependency.

4. **Let tests depend on each other's order.** Every test must be independently runnable via `npx playwright test portfolio/holdings-table.spec.ts`. This requires each test to seed its own state and tear it down. Never rely on "the previous test created the account."

5. **Assert on Recharts SVG internals.** SVG element counts and path `d` attribute values vary by browser version and chart data range. Do not assert `page.locator('path').count() === 7`. Assert on the container's testid and the loading/empty state text instead.

6. **Intercept and mock the component's own API calls to test the component's rendering logic.** The only valid use of route interception in Spec A is to simulate error states or to return canned data for external service calls (Gemini, Plaid, FRED). For happy-path tests, use real DB-seeded data.

---

## 13. Prerequisites: Testability Gaps

The following `data-testid` attributes are required by this spec but are not present in the current components. The eng team must add these before the Playwright suite can be authored. Each gap is noted with the component file that needs the change.

| Component | Gap | Suggested fix |
|---|---|---|
| `AccountScopeChips.tsx` | No `data-testid` on chips | Add `data-testid="scope-chip-all"` to "All investments" button; `data-testid={`scope-chip-${a.id}`}` to per-account buttons |
| `PortfolioTimeSeriesChart.tsx` | No `data-testid` on chart container or overlay buttons | Add `data-testid="timeseries-chart"` to outer `<div>`; `data-testid={`overlay-${key}`}` to each overlay chip button; `data-testid={`window-btn-${w}`}` to each window button in `PortfolioPage` |
| `AllocationStackedBars.tsx` | No `data-testid` on container or bar rows | Add `data-testid="allocation-bars"` to outer `<div>`; `data-testid={`bar-${dim}`}` to each bar row `<div>`; segments already have `title` attribute (reuse for selection assertions) |
| `HoldingsTable.tsx` | No `data-testid` on table, columns, or rows | Add `data-testid="holdings-table"` to outer `<div>`; `data-testid={`col-${key}`}` to each `<Th>`; `data-testid={`holding-row-${h.ticker}`}` to each `<tr>` |
| `AttributionWaterfall.tsx` | No `data-testid` on container, heading, or unattributed banner | Add `data-testid="attribution-waterfall"` to outer `<div>`; `data-testid="attribution-heading"` to `<h3>`; `data-testid="unattributed-banner"` to the amber warning `<div>` |
| `AttributionChips.tsx` | No `data-testid` on container or period summary | Add `data-testid="attribution-chips"` to outer `<div class="space-y-2 mb-2">`; `data-testid="attribution-chips-period"` to the period summary line |
| `UnifiedImportModal.tsx` + `ImportToastProvider.tsx` | (Met) The unified modal already exposes all testids called out in §3.7: `data-testid="unified-import-modal"` on the container; `unified-row`, `unified-row-account`, `unified-row-files`, `unified-row-remove`, `unified-add-row`, `unified-new-name`, `unified-new-type`, `unified-new-save` on row controls; `unified-preview-btn` / `unified-save-btn` on footer; `preview-card` + `preview-card-remove` per group; `bank-balance`, `bank-txn-sort`, `inv-holdings-sort`, `inv-txn-sort` on sort selects; `tie-out-banner` / `tie-out-match` on investment cards; `import-toast` / `import-toast-review` on the post-save toast |
| `PortfolioPage.tsx` | No `data-testid` on Import/Sync buttons, status span, or page root | Add `data-testid="portfolio-page"` to root `<div>`; `data-testid="btn-import-statement"` / `data-testid="btn-sync-plaid"` / `data-testid="sync-status-msg"` |
| `Dashboard.tsx` | No `data-testid` on tab buttons | Add `data-testid={`tab-${tab}`}` to each tab `<button>` in the tab bar |
| `TablePill.tsx` | No `data-testid` on container, toggle, or body | Add `data-testid="table-pill"` to outer `<div>`; `data-testid="table-pill-toggle"` to the `<button>`; `data-testid="table-pill-body"` to the expanded content section |
| `AllocationStackedBars.tsx` + `PortfolioPage.tsx` | `onSelect` prop is passed from `PortfolioPage` to `AllocationStackedBars` but `HoldingsTable` does not accept a filter prop — so clicking a bar segment does not actually filter the table | Either wire a filter param through `HoldingsTable.accountId` extension, or add a `filterDim`/`filterLabel` prop to `HoldingsTable` and add a corresponding `GET /portfolio/holdings?dim=sector&label=Technology` query param to the backend. Until this is resolved, the "click filters HoldingsTable" interaction test is blocked and should be marked `test.skip` with a link to the tracking issue. |
| `backend/app/main.py` | No `/eval/health` endpoint | Add `GET /eval/health` (registered only when `EVAL_MOCKS=1`) returning `{eval_mocks, fred_mocked, gemini_mocked, plaid_mocked}` per §6.4 |

---

## 14. Meta-tests for the Setup Harness

The Spec A harness (`globalSetup`, `seed_runner` CLI, `/eval/health` endpoint, `globalTeardown`, login + storageState helper) is itself code that runs in CI. Without unit tests, a harness bug (silent seed failure, mock-state misreport, login-state stale across tests) produces false test failures — or worse, silent false passes — that erode trust in the entire eval signal.

This is the same gap (and same fix) as Spec B §14 and Spec C §16.

### 14.1 Coverage targets

Every public function in the harness has at least one test. Tests are deterministic (no live API calls) and run alongside the existing pytest suite; they're not part of the Playwright run.

### 14.2 Test files (NEW)

```
backend/tests/evals/frontend/test_harness.py (NEW — Python; runs in pytest)
  ├── test_seed_runner_applies_single_brokerage_fixture
  ├── test_seed_runner_applies_no_holdings_fixture
  ├── test_seed_runner_unknown_fixture_exits_nonzero_with_clear_message
  ├── test_seed_runner_idempotent_across_runs
  ├── test_eval_health_endpoint_returns_mock_state
  ├── test_eval_health_returns_404_when_eval_mocks_unset
  ├── test_eval_health_reports_partial_mock_state_correctly
  ├── test_setup_validation_passes_with_correct_seed
  ├── test_setup_validation_fails_with_missing_seed
  └── test_globalTeardown_truncates_only_eval_user_rows

frontend/e2e/test_harness.spec.ts (NEW — Playwright meta-test, runs once)
  ├── test_globalSetup_completes_before_first_test
  ├── test_storageState_persists_login_across_test_files
  └── test_setup_validation_runs_after_seed
```

### 14.3 Acceptance

- All `test_harness.py` tests run in standard pytest (no separate harness needed).
- `test_harness.spec.ts` runs as the first test in the Playwright suite (use `test.describe.configure({ mode: 'serial' })` and order via filename).
- Suite runs in < 5 seconds for the Python tests; the Playwright meta-test is part of the existing `< 90s` budget.

### 14.4 What meta-tests don't cover

- Surface rendering — that's what the rest of Spec A measures.
- Backend logic — Spec B's responsibility.
- LLM behavior — Spec C's responsibility.

These meta-tests are deliberately small. They verify the harness, not the system under test.

---

*Spec A authored 2026-05-09; revised after architecture review (commit pending).*
