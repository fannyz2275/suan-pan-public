# AGENTS.md

Shared financial-data validation guidance: [Finance Data Audit](docs/finance-data-audit.md).
Use it when changing imports, transfers, balances, or financial summaries.
Local assistant skills/configuration are optional and are not application dependencies.

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

**Suan-Pan (算盘)** is an AI-powered personal finance advisor. Unlike traditional apps showing historical data, it simulates the ripple effects of financial decisions across all user goals simultaneously using a quantitative engine, then explains results in plain language via AI.

## Development Commands

### Backend (FastAPI, Python 3.11+)
```bash
cd backend
uvicorn app.main:app --reload   # Dev server on port 8000
python -m pytest tests/ -v      # Run all tests
```

Dependencies are managed with `uv`. Install with `uv pip install -r requirements.txt` or `pip install -r requirements.txt`.

### Frontend (React + TypeScript + Vite)
```bash
cd frontend
npm install
npm run dev          # Dev server on port 5173
npm run build        # Production build
npm run lint         # ESLint check
```

### Environment Setup
Copy `.env.example` → `.env` in both `backend/` and `frontend/`. Run `backend/supabase/schema.sql` in Supabase SQL Editor once.

**Backend env vars:** `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GOOGLE_API_KEY`, `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`, `FRONTEND_URL`

**Frontend env vars:** `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL`

## Architecture

### Backend (`backend/app/`)
FastAPI app with modular routers, each domain in its own subdirectory:

- **`auth/middleware.py`** — Extracts JWT from Bearer token, validates via Supabase auth. `get_current_user` is the dependency used in all protected routes.
- **`finance/router.py`** — CRUD for accounts, goals, action items, transactions.
- **`engine/`** — The core quantitative modeling layer:
  - `snapshot.py` — Computes liquid/investment/non-current asset breakdown and net worth
  - `feasibility.py` — Scores each goal 0–100 based on monthly surplus × months available ÷ remaining amount
  - `simulation.py` — Re-scores all goals with modified monthly_surplus to show impact of a decision
  - `cashflow.py` — Month-by-month projection including RSU vesting schedule events and active recurring-rule inflows/outflows
  - `monte_carlo.py` — Stochastic portfolio projections (NumPy, seed=42 for deterministic UX)
  - `recurring/` — Recurring payment detection: deterministic heuristic pipeline (normalize → cluster → period → confidence) with LLM tiebreaker for ambiguous clusters. Emits `RecurringRule` objects consumed by `cashflow.py` and `advisor/context.py`. Router at `/engine/recurring/{detect,rules}`; user confirmations become labeled few-shot examples.
- **`advisor/`** — AI chat integration:
  - `context.py` — Builds structured financial snapshot injected into every LLM call (no raw transactions sent)
  - `router.py` — Streaming chat endpoint (Server-Sent Events) using Google Gemini 2.5-Flash
  - `parser.py` — Extracts structured goals/action items from advisor responses
- **`imports/`** — Gemini-powered parsing of free-form text, PDF, and CSV files into accounts/transactions
- **`plaid/`** — Plaid Link token creation, token exchange, and account/transaction sync

### Frontend (`frontend/src/`)
React 19 + React Router 7 SPA:

- **`contexts/AuthContext.tsx`** — Supabase auth state; wraps entire app
- **`lib/api.ts`** — Axios instance that automatically injects Bearer token from Supabase session
- **`pages/Dashboard.tsx`** — Main app page; orchestrates NetWorthCard, GoalCard, CashFlowChart, ChatPanel, ImportModal
- **`components/ImportModal.tsx`** — Multi-step wizard: text/file input → Gemini preview → confirm save

### Database (Supabase PostgreSQL)
8 tables, all with Row-Level Security (`auth.uid() = user_id`). Key tables:
- `accounts` — Supports Plaid linking, RSU vesting schedules (JSONB), property/business valuations
- `goals` — Financial targets with feasibility scores from the engine
- `chat_sessions` / `chat_messages` — Persistent conversation history
- `plaid_items` — Plaid access tokens (server-side only, never exposed to frontend)

## Git Commits

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`

**Breaking changes:** append `!` after the type (`feat!: ...`) or add a `BREAKING CHANGE:` footer.

Examples:
- `feat(advisor): add streaming chat responses`
- `fix(engine): correct feasibility score calculation`
- `feat(api)!: rename /finance/accounts endpoint`

## Key Design Decisions

- **Financial context injection:** Every advisor message includes a structured snapshot of the user's finances — the LLM never sees raw transaction history.
- **Streaming:** Chat responses use Server-Sent Events (`/advisor/chat`).
- **Plaid is optional:** Users can manually import accounts/transactions without linking banks.
- **Monte Carlo is deterministic:** Fixed seed (129) ensures consistent projections for the same inputs.
- **Service key stays backend-only:** Frontend only uses the Supabase anon key; all writes go through FastAPI with service key + RLS enforcement.
- **AI uses Gemini, not Codex:** Despite the finance advisor persona, the LLM calls use Google Gemini 2.5-Flash via `GOOGLE_API_KEY`.

## Imported Claude Cowork project instructions

I'm working on Suan-Pan (算盘), an AI-powered personal finance advisor. Unlike typical apps that
  show historical data, it simulates the ripple effects of financial decisions across all of a
  user's goals simultaneously using a quantitative engine, then explains the results in plain
  language via an LLM.

  Stack

  - Backend: FastAPI (Python 3.11+), Supabase (Postgres + Auth + RLS), Plaid for bank linking,
  Google Gemini 2.5-Flash for LLM, NumPy for Monte Carlo. Managed with uv.
  - Frontend: React 19 + TypeScript + Vite + React Router 7, Supabase JS client, Axios.
  - Dev: uvicorn app.main:app --reload (port 8000), npm run dev (port 5173).

  Architecture

  Backend (backend/app/):
  - auth/middleware.py — get_current_user dependency validates Supabase JWT.
  - finance/router.py — CRUD for accounts, goals, action items, transactions.
  - engine/ — the core quantitative layer:
    - snapshot.py — net worth + asset breakdown (liquid / investment / non-current).
    - feasibility.py — scores each goal 0–100 from surplus × months ÷ remaining.
    - simulation.py — re-scores all goals under a modified surplus (decision impact).
    - cashflow.py — month-by-month projection with RSU vesting + recurring rules.
    - monte_carlo.py — stochastic projections, fixed seed=129 for deterministic UX.
    - recurring/ — heuristic pipeline (normalize → cluster → period → confidence) with LLM
  tiebreaker; emits RecurringRule objects consumed by cashflow + advisor context.
  - advisor/ — Gemini chat with SSE streaming (/advisor/chat); context.py builds a structured
  financial snapshot injected into every call (LLM never sees raw transactions).
  - imports/ — Gemini parses free-form text / PDF / CSV into accounts + transactions.
  - plaid/ — Link token, exchange, account/transaction sync. Tokens stay server-side.

  Frontend (frontend/src/):
  - contexts/AuthContext.tsx wraps the app with Supabase auth state.
  - lib/api.ts Axios instance auto-injects the Bearer token.
  - pages/Dashboard.tsx orchestrates NetWorthCard, GoalCard, CashFlowChart, ChatPanel, ImportModal.

  Database (Supabase): 8 tables, all RLS-gated by auth.uid() = user_id. Notable: accounts supports
  Plaid + RSU vesting JSONB + property/business valuations; chat_sessions/chat_messages hold
  history; plaid_items holds access tokens (server-only).

  Key invariants

  - Financial context to LLM is always the structured snapshot — never raw transactions.
  - Monte Carlo seed is fixed (129).
  - Service key is backend-only; frontend uses anon key + RLS.
  - Advisor uses Gemini, not Claude, despite the persona.
  - Conventional Commits (feat, fix, refactor, etc.); breaking changes use ! or BREAKING CHANGE:
  footer.
  - Supabase schema changes go in backend/supabase/migrations/ as dated SQL files; user must apply
  them in the Supabase SQL Editor before testing.
