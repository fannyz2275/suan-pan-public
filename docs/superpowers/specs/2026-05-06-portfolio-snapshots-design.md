# Portfolio Snapshots & Investment Insights — Design

**Date:** 2026-05-06
**Status:** Draft
**Owner:** fanz2275
**Related:** `backend/app/engine/snapshot.py`, `backend/app/plaid/router.py`, `backend/app/advisor/context.py`

## Problem

Today, brokerage and retirement accounts in Suan-Pan are a single `balance` number. The advisor has no idea what's *in* an investment account, how its composition has changed, or how external events (rates, inflation, sector rotations) line up with the user's actual exposures. Users can't ask things like:

- "What do I own across all investment accounts?"
- "How did my portfolio change in the last quarter — was that the market, my contributions, or a trade I made?"
- "Am I overexposed to tech right now?"
- "How did the March rate move affect me specifically?"

This design adds point-in-time portfolio snapshots, investment-side transactions, and the AI surfaces required for those questions, without rebuilding the rest of the app.

## Scope

### In v1

- Capture holdings per investment account from **Plaid investments endpoints** (auto) and **statement imports** (Gemini-parsed Schwab/Fidelity/Vanguard PDFs/text/CSVs).
- Capture **investment transactions** (buy / sell / dividend / interest / fee / transfer / split / reinvest) from the same two sources.
- **Lazy-daily** snapshot cadence: on any read of the portfolio view, if today's snapshot doesn't exist for an account, take one synchronously. No background scheduler.
- **Carry-forward** time-series: between observed snapshots, revalue the most recent prior holdings using yfinance daily close prices.
- **3-dimension exposure** (asset class · sector · region) with **top-10 ETF look-through**: top-10 holdings of each ETF contribute weighted to underlying sector/region; residual stays in the ETF's category.
- **New "Portfolio" tab on the Dashboard**, with account-scope chips (All investments / per-account).
- **Time windows**: 1M / 3M / 6M / YTD / 1Y / All + custom range.
- **Allocation visualization**: three stacked horizontal bars (asset class · sector · region) shown simultaneously; clicking a slice filters the holdings table.
- **Time-series chart**: total portfolio value over the selected window, with optional FRED overlays (10Y yield, CPI YoY, SPY return).
- **Attribution waterfall** on the Portfolio page: start → market → contributions → trades → dividends → end. Page-level UI is quantitative only — no inline narrative.
- **Advisor narrative**: when the user asks portfolio questions in chat, the advisor calls new MCP tools (`portfolio_get_holdings`, `portfolio_get_exposure`, `portfolio_get_attribution`) and returns chip+prose explanations. All AI narration lives in the chat surface, not on the Portfolio page.

### Out of v1

- Background scheduler / cron-driven daily snapshots.
- Paid market-data and news APIs (Polygon, Alpha Vantage paid tier, NewsAPI, Marketaux).
- Full ETF look-through beyond top-10 (no proprietary holdings databases).
- Tax-lot accounting and realized gain reporting.
- Options, futures, crypto staking yield, alternative-asset performance.
- Cross-account benchmark tracking ("vs. a 60/40 portfolio") beyond the simple SPY overlay.

## Architecture

### Data flow

```
                ┌─ Plaid /investments/holdings/get ─┐
                ├─ Plaid /investments/transactions ─┤
Account-level ──┤                                   ├─→ portfolio_snapshots
data sources    ├─ Statement import (Gemini parse) ─┤   + snapshot_holdings
                └─ Manual holdings entry ───────────┘   + investment_transactions
                                                              │
                                            ┌─────────────────┴────────────────┐
                                            ↓                                  ↓
                                   security_reference                 Portfolio engine
                                  (yfinance enrich)                  (app/portfolio/)
                                  - sector, asset class               - revalue / carry-fwd
                                  - region, top-10 look-through       - exposure (3 dims)
                                            ↓                         - change attribution
                                   security_prices                            │
                                  (yfinance, daily close)                     ↓
                                                                  ┌───────────┴──────────┐
                                                                  ↓                      ↓
                                                            /portfolio router       MCP tools
                                                            (REST endpoints)        (advisor reads)
                                                                                          ↓
                                                                          Advisor narrates change
                                                                          attribution in chat only
```

### Module layout

```
backend/app/
├── portfolio/
│   ├── __init__.py
│   ├── router.py            # FastAPI endpoints
│   ├── schemas.py           # Pydantic models
│   ├── snapshots.py         # Read/write snapshots; lazy-create today's on read
│   ├── reval.py             # Carry-forward + yfinance revaluation
│   ├── attribution.py       # Decompose period change → market / contrib / trades / div
│   ├── exposure.py          # 3-dim allocation w/ top-10 look-through
│   └── reference.py         # Security enrichment via yfinance + caching
├── plaid/router.py          # + /investments/sync endpoint (holdings + txns)
├── imports/parser.py        # + investment-statement schema
├── advisor/context.py       # + portfolio block (latest snapshot, top 5 holdings, asset-class %)
└── mcp/tools.py             # + portfolio_get_holdings, portfolio_get_exposure,
                             #   portfolio_get_attribution

frontend/src/
├── pages/Dashboard.tsx      # + "Portfolio" tab
└── components/portfolio/
    ├── PortfolioPage.tsx
    ├── AccountScopeChips.tsx
    ├── PortfolioTimeSeriesChart.tsx
    ├── AllocationStackedBars.tsx
    ├── HoldingsTable.tsx
    ├── AttributionWaterfall.tsx
    └── PortfolioImportModal.tsx
```

## Data model

All new tables live in `public.` schema with RLS scoped to `auth.uid() = user_id` (matching existing patterns). Migration filename: `backend/supabase/migrations/2026-05-06-portfolio-snapshots.sql`.

Tables are created in dependency order (`security_reference` first since `snapshot_holdings` and `investment_transactions` reference it).

```sql
-- One row per ticker we've ever encountered. Enriched once, reused everywhere.
create table public.security_reference (
  id uuid default uuid_generate_v4() primary key,
  ticker text unique not null,
  name text,
  security_type text,                           -- stock, etf, mutual_fund, bond, crypto, other
  asset_class text,                             -- equity, fixed_income, cash, commodity, crypto, other
  sector text null,                             -- GICS for individual equities
  region text null,                             -- US, Developed, Emerging, Global
  look_through jsonb null,                      -- [{ticker, weight, sector, region}, ...] top-10 for ETFs/funds
  enriched_at timestamptz,
  enrichment_source text                        -- 'yfinance', 'manual'
);

-- Real holdings observations. Multiple rows per account allowed (one per snapshot_date),
-- multiple sources can coexist (e.g., Plaid + statement import on same day).
create table public.portfolio_snapshots (
  id uuid default uuid_generate_v4() primary key,
  user_id uuid references auth.users(id) not null,
  account_id uuid references public.accounts(id) on delete cascade not null,
  snapshot_date date not null,
  source text check (source in ('plaid','statement_import','manual')) not null,
  total_value numeric(15,2) not null,
  cash_value numeric(15,2) default 0,           -- uninvested cash inside the account
  superseded_at timestamptz null,               -- set when a newer same-day snapshot wins
  created_at timestamptz default now(),
  unique (account_id, snapshot_date, source)
);

create index portfolio_snapshots_user_date_idx
  on public.portfolio_snapshots (user_id, snapshot_date desc)
  where superseded_at is null;

-- Normalized holdings. One row per ticker per snapshot.
create table public.snapshot_holdings (
  id uuid default uuid_generate_v4() primary key,
  snapshot_id uuid references public.portfolio_snapshots(id) on delete cascade not null,
  ticker text not null,
  security_id uuid references public.security_reference(id),
  quantity numeric(20,8) not null,
  price numeric(15,4) not null,                 -- as-of snapshot_date
  market_value numeric(15,2) not null,
  cost_basis numeric(15,2) null,
  unrealized_gain numeric(15,2) null
);

create index snapshot_holdings_ticker_idx
  on public.snapshot_holdings (ticker);

-- Investment transactions. Separate from the cash transactions table
-- because they have different fields (qty, price, security) and different semantics
-- (a "buy" is not a cash expense in the cash-flow chart).
-- amount is signed cash impact: negative = cash leaving the account (buy, fee, withdrawal),
-- positive = cash arriving (sell, dividend, deposit). Reinvested dividends are recorded
-- as a single row with type='reinvest' and amount=0 (cash impact nets to zero).
create table public.investment_transactions (
  id uuid default uuid_generate_v4() primary key,
  user_id uuid references auth.users(id) not null,
  account_id uuid references public.accounts(id) on delete cascade not null,
  date date not null,
  type text check (type in (
    'buy','sell','dividend','interest','fee',
    'transfer_in','transfer_out','split','reinvest'
  )) not null,
  ticker text null,
  security_id uuid references public.security_reference(id),
  quantity numeric(20,8) null,
  price numeric(15,4) null,
  amount numeric(15,2) not null,                -- signed: see comment above
  source text check (source in ('plaid','statement_import','manual')) not null,
  plaid_investment_transaction_id text unique null,
  created_at timestamptz default now()
);

create index investment_txns_user_date_idx
  on public.investment_transactions (user_id, date desc);

-- Daily close cache. Used by reval, attribution, and time-series.
create table public.security_prices (
  ticker text not null,
  date date not null,
  close numeric(15,4) not null,
  primary key (ticker, date)
);

-- RLS
alter table public.portfolio_snapshots enable row level security;
alter table public.snapshot_holdings enable row level security;
alter table public.investment_transactions enable row level security;
alter table public.security_reference enable row level security;
alter table public.security_prices enable row level security;

create policy "portfolio_snapshots_own" on public.portfolio_snapshots
  using (auth.uid() = user_id);

create policy "snapshot_holdings_own" on public.snapshot_holdings
  using (snapshot_id in (
    select id from public.portfolio_snapshots where user_id = auth.uid()
  ));

create policy "investment_transactions_own" on public.investment_transactions
  using (auth.uid() = user_id);

-- Reference + price tables are read-mostly and shared across users; write through service role only.
create policy "security_reference_read_all" on public.security_reference
  for select using (true);
create policy "security_prices_read_all" on public.security_prices
  for select using (true);
```

`accounts.balance` for `type in ('brokerage','retirement')` becomes a denormalized cache of the most recent non-superseded snapshot's `total_value` so existing engine code (`snapshot.py`, `feasibility.py`) keeps working unchanged.

## Component design

### Snapshot lifecycle (`portfolio/snapshots.py`)

Snapshots are stored only when they are real observations — never synthesized. Carry-forward is a read-time computation in `reval.py`, not a write path.

- `ensure_today_snapshot(account_id)` — Called on Portfolio page reads:
  - For Plaid-linked investment accounts: if the last item-level Plaid sync was more than 24 hours ago, call `/investments/sync`, persist a snapshot with `source = 'plaid'` and the holdings/txns returned.
  - For accounts without Plaid linkage: no-op. Snapshots for manual accounts are written only via the manual entry endpoint or the statement import flow.
  - For accounts with no snapshots at all: no-op. The UI surfaces a "Connect Plaid or import a statement" empty state.
- Same-day collision: when a new snapshot lands and a prior same-day snapshot exists from a *different* source, the older one's `superseded_at` is set to `now()` and it stays in history. The newer source wins for current-state queries.

### Carry-forward revaluation (`portfolio/reval.py`)

- `timeseries(account_id, from_date, to_date)` — Returns a list of `(date, total_value)` tuples covering every business day in the window:
  - Anchors on the most recent snapshot ≤ `from_date` (or the first snapshot ever, if none earlier).
  - For each business day `d` in `[from_date, to_date]`: pick the most recent snapshot with `snapshot_date ≤ d`; for each holding, `value(d) = quantity × close_price(ticker, d)` from `security_prices` (carrying forward if missing); sum.
  - Investment transactions between snapshots are ignored at this layer — they don't change the carry-forward holdings (the next snapshot will reflect them). Attribution handles them separately.
- Prices are fetched in bulk per ticker for the full window, cached, and reused.

### Exposure with look-through (`portfolio/exposure.py`)

- `exposure(snapshot_id, dimension)` where dimension ∈ `{asset_class, sector, region}`:
  - For each holding: look up `security_reference`. If `look_through` is non-null and the dimension is `sector` or `region`, distribute `market_value × weight` across the top-10's labels; the residual `1 - sum(weights)` stays in the ETF's own `sector`/`region` (or `'Other'` if null).
  - For `asset_class`: no look-through (an equity ETF stays equity); use the ETF's own `asset_class`.
  - Returns `[{label, market_value, percent}, ...]` sorted descending.

### Change attribution (`portfolio/attribution.py`)

- `attribution(account_id, from_date, to_date)` decomposes total change into four buckets using the cash-impact identity. All `investment_transactions.amount` values are signed (positive = cash arriving in the account, negative = cash leaving):
  - `start_value` = portfolio value at `from_date` (carry-forward + prices).
  - `end_value` = portfolio value at `to_date`.
  - `flows` = sum of `transfer_in + transfer_out` amounts in `[from_date, to_date]`. Positive = net contributions; negative = net withdrawals. The UI splits this into separate "contributions" and "withdrawals" buckets at render time.
  - `dividends` = sum of `dividend + interest` amounts in window. (Reinvested dividends appear as `dividend` cash arriving plus a separate `reinvest` row at zero net cash, so they're counted once here.)
  - `trades` = realized P&L from `buy/sell` rows in window. When prior snapshots carry `cost_basis`, compute realized gain via FIFO. When basis is missing, fall back to `trade_impact = (sum of sell amounts) + (sum of buy amounts)` — buy amounts are negative, so this nets to a signed cash-flow figure rather than a true P&L; the bucket is labeled "trades (no basis)" so the UI doesn't claim accuracy it doesn't have.
  - `market` = `end_value - start_value - flows - dividends - trades` (residual).
- The market residual is the integrity check: if any of the above is missing or stale, the residual absorbs the error and is labeled "market & other."

### Security enrichment (`portfolio/reference.py`)

- On first encounter of a ticker (snapshot ingest, txn ingest, manual entry), enqueue an enrichment job that:
  - Calls `yfinance.Ticker(ticker).info` → name, type, sector, country.
  - Maps country → region using a static lookup table.
  - For ETF/fund: calls `yfinance.Ticker(ticker).funds_data.top_holdings` (or equivalent) → store top-10 with weights, enriching each underlying ticker recursively (one level only, to bound work).
  - Failures result in `asset_class = 'other'` and a flag for manual review.
- Enrichment is best-effort and async — UI never blocks on it.

### Statement import (`imports/parser.py`)

- New schema mode `investment_statement` with prompt asking Gemini to extract:
  - Account-level metadata (account number, statement period, total value).
  - Holdings list (ticker, qty, price, market value, optional cost basis).
  - Activity / transaction list (date, type, ticker, qty, price, amount).
- Returns the same preview UI as the existing cash-import flow. On confirmation, writes a snapshot for the period-end date and investment transactions for the period.

## API surface

```
GET  /portfolio/summary?window=3M&account_id=…    → { total_value, period_change, top_holdings[5] }
GET  /portfolio/timeseries?window=3M&account_id=… → [{ date, total_value, fred_overlays? }]
GET  /portfolio/holdings?as_of=…&account_id=…     → [{ ticker, name, qty, price, market_value, percent, period_change }]
GET  /portfolio/exposure?dim=sector&as_of=…       → [{ label, market_value, percent }]
GET  /portfolio/attribution?from=…&to=…           → { start, end, market, contributions, withdrawals, trades, dividends }
POST /portfolio/snapshot/manual                   → body: { account_id, holdings[] } → snapshot
POST /portfolio/import/statement                  → body: { account_id, raw_text|file } → preview
POST /portfolio/import/statement/confirm          → body: { preview_id, edits? } → snapshot + txns
```

`account_id` omitted = household roll-up across all investment accounts.

## Frontend

- `Dashboard.tsx` adds a fourth top-level tab: "Portfolio" (after Overview / Cash flow / Goals).
- `PortfolioPage.tsx` orchestrates:
  - `AccountScopeChips` — pill row, default "All investments".
  - `PortfolioTimeSeriesChart` — total value line; window picker (1M/3M/6M/YTD/1Y/All/custom); FRED overlay toggles (10Y · CPI · SPY) using existing chart library (`recharts`, matching `CashFlowChart`).
  - `AttributionWaterfall` — start → +market → +contrib → ±trades → ±dividends → end, no inline prose.
  - `AllocationStackedBars` — three stacked bars (asset class · sector · region), each segment clickable to filter `HoldingsTable`.
  - `HoldingsTable` — sortable columns: ticker · name · qty · MV · % of portfolio · period Δ.
  - `PortfolioImportModal` — entry point: paste text or upload PDF/CSV, runs through `/portfolio/import/statement`, shows preview, confirms.
- All AI narrative happens in `ChatPanel`. Page surface is quantitative only.

## AI integration

Three new MCP tools (registered in `backend/app/mcp/tools.py`):

- `portfolio_get_holdings(as_of?, account_id?)` — returns holdings list. Used for "what do I own."
- `portfolio_get_exposure(as_of?, account_id?, dimension?)` — returns 3-dim allocation. Used for "am I too tech / too US / too equity-heavy."
- `portfolio_get_attribution(from, to, account_id?)` — returns the change decomposition + a small `macro_context` payload pulled from FRED (10Y change in window, CPI YoY at end, SPY return in window). Used for "why did my portfolio move."

The advisor system prompt gets a tiny portfolio block (in `advisor/context.py`):

```
PORTFOLIO (latest snapshot YYYY-MM-DD):
  Total: $X,XXX,XXX across N accounts
  Top holdings: NVDA 12% · VOO 9% · AAPL 6% · BND 5% · MSFT 4%
  Asset class: equity 62% · FI 22% · cash 8% · other 8%
```

Detailed holdings, period attribution, and per-ticker numbers come from tool calls — not the prompt — to keep tokens bounded. The chat renders attribution responses as the chip+prose form (the "B" mockup), reusing the existing `ChatMessage` table-card pattern.

## Error handling and edge cases

- **yfinance flakiness or rate limits.** All yfinance calls go through a small wrapper with retry + backoff. Prices are cached aggressively in `security_prices`. Missing prices on a date carry forward from the most recent prior close (with a max-staleness flag of 7 calendar days; older than that, the holding's value for that day is null and the UI shows a gap).
- **Unknown ticker.** Stored with `asset_class = 'other'`, flagged in `security_reference.enriched_at IS NULL`. Holdings still appear in totals; exposure attributes them to "Other."
- **Stale Plaid sync.** Lazy snapshot creation re-syncs Plaid if the last item-level sync was >24h ago. Retries on transient errors; surfaces a banner if Plaid is in `ITEM_LOGIN_REQUIRED`.
- **Same-day snapshots from multiple sources.** Newer source wins for current-state queries; older snapshot is preserved with `superseded_at` for audit.
- **Statement import parsing failures.** Surface raw text + parsed preview side-by-side, allow inline edits before confirm — same UX as existing cash imports.
- **Account deleted.** `on delete cascade` on snapshots and txns drops history with the account.
- **Cost basis missing.** Attribution falls back to the simpler "trade impact" formula and labels the bucket "trades (no basis)" instead of "realized P&L."

## Testing

- **Unit tests** (`backend/tests/portfolio/`):
  - `test_reval.py` — carry-forward correctness across gaps; price-missing fallback; bulk-fetch caching.
  - `test_attribution.py` — identity check (`start + flows + market = end`); FIFO basis when available; fallback path when basis is missing.
  - `test_exposure.py` — top-10 look-through weighting; residual handling; unknown-ticker bucketing.
  - `test_reference.py` — yfinance enrichment with mocked responses; ETF look-through one-level recursion bound.
- **Integration tests:**
  - Plaid investments sandbox end-to-end: holdings + txns + snapshot creation.
  - Statement import: 2-3 sanitized fixture statements (Schwab, Fidelity, Vanguard) → preview → confirm → snapshot row matches expected.
  - MCP tool calls: each of the three portfolio tools returns the correct shape from a seeded fixture.
- **UI / Playwright** (`frontend/tests/`):
  - Open Portfolio tab → switch account scope → switch time window → assert chart updates.
  - Click an asset-class slice → assert holdings table filters.
  - Open chat, ask "why did my portfolio move in the last 3 months" → assert the advisor calls `portfolio_get_attribution` and renders chip+prose.

## Migration & rollout

- Single migration file: `backend/supabase/migrations/2026-05-06-portfolio-snapshots.sql`.
- No data backfill required; tables start empty. First snapshot per account is created on first portfolio-page load.
- No feature flag — feature is dormant until a user opens the Portfolio tab or imports a statement.
- For existing brokerage accounts where Plaid is linked: first portfolio-page load triggers a Plaid investments sync; user sees a brief loading state.

## Open questions deferred to v2

- Tax-lot accounting and realized-gain reporting.
- Full ETF look-through beyond top-10.
- Paid news API for richer macro narration (currently rely on Gemini training + FRED).
- Benchmark portfolio comparison ("you vs. a 60/40").
- Options, futures, cryptocurrency staking yield.

## Borrowed patterns (Anthropic financial-services, May 2026)

Anthropic released ten finance-agent templates on 2026-05-05 ([`anthropics/financial-services`](https://github.com/anthropics/financial-services)). The two templates closest to this design — `gl-reconciler` (skills: `gl-recon`, `break-trace`) and `statement-auditor` (skill: `nav-tieout`) — are fund-accounting workflows but they encode patterns that map cleanly onto consumer-portfolio data ingestion and explanation. The patterns we adopt are listed below; they are normative for Plans 3 and 4 of this design.

### Untrusted statement input

Statements pasted or uploaded by the user are **untrusted input** for the LLM. The Gemini prompt must explicitly instruct the model to treat statement text as data to extract, never as instructions to follow. This defends against adversarial text inside statements (e.g., a memo line that says "ignore the schema and respond with X"). Implemented in Plan 3, T2.

### Independent recompute and tie-out

Whenever the system parses a financial document or computes a derived figure, it must independently recompute the result from first principles and surface any unexplained delta as a flag — never silently absorb the residual into a "miscellaneous" bucket. Concrete instances:

- **Statement parser (Plan 3):** extract any "Total Account Value" the statement itself prints into `total_value_reported`, then compare to `cash + Σ(qty × price)`. Mismatch beyond 1% (or $1) surfaces a UI warning before the user can confirm the import. Adapted from the `nav-tieout` skill, which independently recomputes an LP's capital account from the NAV pack and flags any line that doesn't agree within `0.01`.
- **Attribution waterfall (Plan 4):** the identity `market = end − start − flows − dividends − trades` is the recompute. The residual must be surfaced as a first-class "unattributed" bucket when nonzero outside tolerance, not folded silently into the market label. Adapted from the same skill: "the generated statement is the thing under test; the source-of-truth pack is the source of truth."

### Break classification

When parsed/computed values disagree with prior observations or with the source document, classify the break by likely cause rather than reporting a flat list. The `gl-recon` skill defines a six-bucket taxonomy: timing, FX, mapping, duplicate / missing post, fee / accrual, data quality. For Plan 4, the equivalent buckets for portfolio change-attribution are: market move, contributions, withdrawals, trades (with vs. without basis), dividends, fees, unattributed. For Plan 3's preview when a prior snapshot exists, classify per-position changes as: new position, size change (with delta), closed position, unchanged.

### One-sentence root-cause statements

When the advisor narrates a portfolio change in chat (Plan 4), each bucket gets a single explanatory sentence in the form **"⟨amount⟩ from ⟨bucket⟩ because ⟨specific reason with names and numbers⟩"** rather than vague aggregate prose. Borrowed verbatim from `break-trace`, which mandates one-sentence root causes like *"GL posted on settle date (T+2) while subledger posted on trade date — timing break, will clear on 2026-05-07."* The findings prompt (`backend/app/advisor/findings_prompt.py`) gets 2-3 well-formed examples as few-shot demonstrations.

### Read-only AI tools

The advisor's MCP toolset is read-only by design. There is no `portfolio_write_*` tool exposed to the model. Anything that mutates state (creating snapshots, importing statements, confirming holdings) goes through a confirm step in the UI, not a tool call. Plan 4's three tools (`portfolio_get_holdings`, `portfolio_get_exposure`, `portfolio_get_attribution`) honor this, and future plans must not add a write tool without revisiting the threat model. Borrowed from the `statement-auditor` and `gl-reconciler` agents, where reader subagents have no MCP access and only the resolver subagent holds Write — and even the resolver never touches the ledger directly.

### Patterns intentionally not copied

- Enterprise-data MCP connectors (Daloopa, FactSet, Moody's). Suan-Pan stays with Plaid + yfinance + manual import.
- Multi-LP fund accounting (waterfall, carried interest, NAV pack). The recompute pattern ports; the domain doesn't.
- Multi-subagent orchestration with strict per-role tool segregation. Overkill for our single-router-with-MCP-tools size.
- xlsx-author / pptx-author deliverables. We have a web UI.
