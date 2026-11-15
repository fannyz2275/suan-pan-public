# Suan-Pan

**Understand where your money went, what you kept, and what you can do next.**

Your bank balance tells you how much you have. It does not tell you whether you
are spending less, saving more, or simply moving money between accounts.

Suan-Pan brings your statements, spending, investments, and goals into a personal
finance workspace. Review the numbers, explore what changed, and open an AI
advisor when you want help making sense of them.

**Overview · Spending · Wealth · Plan**

> Early-stage, self-hosted software. Run it locally with your own services and API
> credentials. Some advisor capabilities are experimental and disabled by default;
> see [Current status](#current-status).

**Get started:** [Documentation](docs/README.md) · [Local setup](#run-it-yourself) · [Troubleshooting](#troubleshooting) · [Contributor checks](#for-contributors)

## A clearer picture of your money

### Know what you actually kept

See monthly income, spending, money kept, and savings rate together. Compare
periods, then drill into categories and transactions instead of stopping at a
single total.

Review possible transfers so moving money to another account does not get
mistaken for everyday spending. Review refund candidates rather than assuming
every credit is income.

Recurring-payment detection groups repeated transactions into proposed income or
payment schedules. Confirm, edit, or reject suggestions; active schedules feed
the cash forecast. Your confirmations and rejections help guide later scans.
Review the dates and amounts, since an apparent pattern may not continue.

### See more than your portfolio balance

Keep accounts and investments in the same workspace. Explore holdings,
allocation, and available net-worth history. Where the data supports it, see
investment contributions separately from unrealized gains and losses.

A deposit is not an investment return. An unrealized gain against cost basis is
not necessarily this month's gain. Missing history matters, and the distinction
should stay visible.

Portfolio records use dated holdings snapshots from statement imports, manual
entry, or optional Plaid investment sync. Review allocation by asset class,
sector, region, or country. Where Yahoo Finance supplies fund composition,
look-through views show underlying stock exposure across ETFs and mutual funds.
Missing composition limits coverage; it does not imply no exposure.

Portfolio history and attribution views help separate contributions, withdrawals,
dividends, trading effects, and estimated market movement. The breakdown depends
on available snapshots, prices, transactions, and cost basis. An unexplained
residual is not proof of a verified investment return.

### Connect today's choices to your goals

Open **Plan** for a shared cash-and-wealth forecast, including a three-month cash
outlook and investment-growth ranges over 1, 5, 10, or 30 years. Recurring income,
bills, everyday spending, and dated life goals feed the same monthly calculation.
A wedding reduces cash once; investment contributions move money between your
accounts without creating wealth; savings targets reserve money without treating
it as spending.

**Forecast assumptions** lists the source and amount behind each estimate. Toggle
an item, change a cost or date, or adjust your cash reserve and investing policy.
The chart, monthly numbers, and goal-funding results update together. Your
overrides are saved and take precedence over subsequent source updates.

The forecast uses 2,000 Monte Carlo paths with a fixed seed of 129. Uncertainty
applies to investment returns, not income or spending. Results are nominal future
dollars; taxes, inflation, debt interest, and automatic investment sales are not
modeled. It starts next calendar month using latest imported balances and omits
remaining current-month activity. Treat it as an inspectable scenario, not a
promise or a fully calibrated financial plan.

### Ask for an explanation when you need one

Open the advisor on demand, or use **Explain this** beside supported metrics to
bring that context into the conversation. Ask follow-ups and give feedback when
an answer misses the point. Your dashboard stays useful without keeping a chat
panel permanently open.

### Carry your priorities into the next conversation

The memory system can extract durable facts, preferences, and corrections from
conversations and save them as notes for later advice. For example, a preference
not to withdraw retirement savings early can inform future discussions of how
to fund a life goal. Relevant notes are retrieved alongside current financial
data, so you do not have to explain the same priorities every time.

The conversation-memory extractor also saves structured future spending plans.
Once a cost and future month are available, the event enters the forecast
automatically, with no confirmation step. Missing details remain visible as
**Not modeled yet**. Linked goals and memory events are consolidated; date-only
updates preserve known costs, and cancellations retire remembered events. Manual
forecast overrides remain under your control.

Memory extraction runs after an idle conversation through the configured Gemini
service; it is not an immediate or fully offline operation. Existing free-text
notes are not automatically converted into numeric plans. Memory is updated
context, not model retraining: live balances stay in financial records, and
improvement on unseen questions is not yet demonstrated.

The advisor combines recent conversation history, durable profile preferences,
current financial metrics, and relevant retrieved notes. Current balances and
income calculations come from financial records rather than remembered profile
amounts. Retrieved facts and preferences can still become stale; review them in
**Settings → What Suan-Pan remembers**, where **Forget** retires a note from future
retrieval. **What Suan-Pan has learned** also lets you inspect and forget learned
policy overrides. Forgetting a note does not delete the source conversation or
recall information already sent to an AI provider.

See [forecast design and validation](docs/forecast.md) for the accounting rules,
source precedence, limitations, and reproducible synthetic-data UI checks.

## Try your first monthly review

After [starting the app](#run-it-yourself):

1. **Add your accounts.** Open **Wealth → Accounts** and create the accounts you
   want to track. Start with statement imports; linking a bank is optional.
2. **Import statements.** Choose **Import statements**, select the destination
   account, and upload a file. For a statement containing several accounts, choose
   the multiple-account option and review the destinations for each section.
3. **Check before saving.** Review the parsed rows and balances. Resolve account
   matches and review possible transfers. Importing is a review step, not a reason
   to trust every parsed value automatically.
4. **Open Overview.** Pick a completed month and look at income, spending, and
   money kept. Import the preceding month too for a useful comparison.
5. **Investigate one change.** In **Spending**, inspect categories, underlying
   transactions, and recurring charges. Open the advisor from a metric when you
   want an explanation.
6. **Turn the review into a plan.** Check **Wealth**, then open **Plan** to review
   your cash outlook and goals. Try a different saving assumption and compare it
   with your current plan.

Start with a small set of statements you can verify. Add more accounts and history
as you become comfortable with the results. Month-end balances across the same
accounts are especially useful for understanding changes in total wealth.

### Questions to bring to the advisor

These are example questions, not a guarantee that every answer is available from
your current data:

> Explain my income for the latest complete month. What changed from the month before?

> Which categories contributed most to my spending change? Show me what to check.

> Is this increase money I added to my investments, or investment performance?

> What happens to my goals if I save an extra $200 each month?

### Finance-specific analysis, designed for reliability

The experimental advisor separates calculating your finances from explaining
them. Backend tools calculate totals, rank the biggest contributors, and check
that the parts add up. Each tool supplies fixed metric definitions alongside its
results, so the model interprets numbers with a consistent meaning instead of
inventing its own calculations.

This approach is tailored to personal-finance questions and tested against
finance-specific cases. It reduces reliance on model arithmetic, but does not
guarantee correct interpretations. It is currently opt-in: the default chat does
not use this newer analysis path. Enabling it requires the relevant database
migrations and `EVIDENCE_ADVISOR_ENABLED=true`; review the limitations in
[Current status](#current-status) first.

## Why not just use ChatGPT?

ChatGPT can help analyze financial inputs and create editable forecasts, including
[cash-flow workbooks with scenarios and assumptions](https://learn.chatgpt.com/use-cases/cash-flow-forecast).
Suan-Pan is not based on a claim that general-purpose AI cannot do finance.

**The difference is the ready-made personal-finance workflow around the conversation.**

With Suan-Pan, you can run the application on your own computer and maintain a
financial workspace connected to your own service accounts. Your account
structure, imported records, goals, and review history provide continuity without
having to reconstruct your financial situation in each new general-purpose chat.
The code is inspectable, including the calculations and the context sent to AI.
Local hosting gives you more control over the deployment; it does not by itself
keep data away from external services.

| What you want to do | What Suan-Pan puts in one place |
| --- | --- |
| Review your finances each month | Saved accounts and transactions, a month selector, and spending and savings views |
| Bring several statements together | Account selection, multi-account matching, parsed-row previews, and import review |
| Understand a number | Category and transaction drill-down, with contextual advisor entry points |
| Separate spending from money movement | Transfer review alongside your account data |
| Keep investments in perspective | Holdings, allocation, contributions, and available growth history |
| Connect a decision to your plans | Cash outlook, goals, and scenario calculations |

Use ChatGPT when you want an open-ended discussion or a custom analysis. Try
Suan-Pan when you want a dedicated place to return to for your own financial
review, with the account structure and review steps already built in. The tools
can complement each other; this is not a benchmark claim of better accuracy.

## Your data and your expectations

- **Your deployment, your workspace.** Run the frontend and backend locally with
  your own credentials and Supabase project, rather than handing your financial
  workspace to a centrally operated Suan-Pan service. You control the imported
  records and configured services, and can inspect how your data is processed.
- **Bank linking is optional.** Manual imports work without Plaid. Plaid sandbox
  connections are demonstrations, not access to real bank accounts.
- **Self-hosted does not mean fully offline.** Authentication and stored data use
  your configured Supabase project. AI-powered imports send statement content to
  the configured model provider; advisor calls send financial context and messages.
  Review provider policies before using sensitive records.
- **Your goals and messages can also be sensitive.** Local hosting is not a
  promise of private or offline AI: financial context and conversation content
  sent to a provider are subject to that provider's policies. Include only what
  you are comfortable sharing with the services you configure.
- **Financial explanations are grounded in defined metrics.** The experimental
  finance-specific analysis path calculates and ranks metrics in code before the
  model explains them. Its checks support reliability, not a guarantee of accuracy.
- **Keep credentials private.** Provider keys and the Supabase service key belong
  on the backend. Never commit real credentials or personal statements.
- **Check important decisions against your records.** Parsing, categorization,
  forecasts, and AI explanations can be wrong. Suan-Pan is not a substitute for
  qualified financial, tax, or legal advice.

## Current status

The app includes statement import and review, spending and savings summaries,
account and portfolio views, cash outlook, goals, scenarios, and contextual chat.
Coverage depends on the data you import and the services you configure.

The newer **finance-specific analysis mode** is experimental and defaults
to off. It includes income and wealth tool chains, required factual statements,
and a saved missing-data/resume flow. Targeted evaluations have passed, but the
broader conversation suite still has failures. Do not treat it as generally
validated or enable it without reviewing the required migrations and limitations.

Feedback and memory mechanisms are also under development. The project does not
yet demonstrate that memory updates improve performance on unseen questions.
See the [evaluation workflow](docs/feature-evaluation-workflow.md) and
[offline evaluation guide](backend/tests/evals/chat/OFFLINE.md) for methodology.

## Run it yourself

This guide runs the frontend and backend on your computer, with a hosted Supabase
project for authentication and storage. It is not a fully offline installation.
Commands below use macOS/Linux or Windows with WSL, and start in the repository
root unless stated otherwise.

### 1. Install prerequisites and download the code

You need Git, Python **3.11**, `uv`, and Node.js **22.13 or later in the 22.x series**
with npm. These versions cover the checked-in Python and frontend dependencies.
You also need your own Supabase project. Plaid is optional.

```bash
git clone https://github.com/fannyz2275/suan-pan.git
cd suan-pan
uv sync --locked --python 3.11
cd frontend
npm ci
cd ..
```

For an existing checkout, skip cloning and run the dependency commands from its
root. Do not replace an existing `.env` when updating the app.

### 2. Create the database

In your Supabase project's **SQL Editor**, paste the entire contents of
[backend/supabase/schema.sql](backend/supabase/schema.sql) and click **Run** once.
This single file includes the base tables, policies, functions, and all current
migrations, including encrypted provider-key storage. It runs in a transaction;
if any statement fails, the setup is rolled back. Fix the reported error before
retrying the whole file.

Use this setup file only on a **fresh** project. Do not run the individual
migration files afterward: they are already included. The app does not apply SQL
automatically. For an existing project, apply only outstanding migrations and
keep a record of applied files; see the [migration guide](backend/supabase/migrations/README.md).

In Supabase Authentication, enable email/password sign-in. Set the Site URL to
`http://localhost:5173` and allow `http://localhost:5173/reset-password` in the
redirect URL configuration. If email confirmation is enabled, users must confirm
their email before signing in. Use the same hostname consistently; add matching
URLs if you choose `127.0.0.1` instead.

### 3. Create private environment files

Copy the templates **only if these files do not already exist**:

```bash
cp -n backend/.env.example backend/.env
cp -n frontend/.env.example frontend/.env
chmod 600 backend/.env frontend/.env
```

Edit `backend/.env` with values from **your** Supabase project:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-backend-service-role-key
FRONTEND_URL=http://localhost:5173
EVAL_MOCKS=0
EVIDENCE_ADVISOR_ENABLED=false
PROVIDER_KEYS_ENCRYPTION_KEYS=
PROVIDER_KEYS_ACTIVE_VERSION=v1
```

Keep `EVAL_MOCKS=0`, the safe default. Set it to `1` only for an isolated
evaluation environment with synthetic users and data. Leave `GOOGLE_API_KEY` and
`OPENROUTER_API_KEY` empty for ordinary app usage; users save those keys in Settings.
Keep the optional Plaid settings unchanged until you need bank linking. Market
prices and security metadata use Yahoo Finance through `yfinance`; no market-data
API key is required. Coverage varies by ticker; unavailable prices remain unpriced.

Edit `frontend/.env`:

```dotenv
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-supabase-publishable-or-anon-key
VITE_API_URL=http://localhost:8000
```

Both files must point to the **same Supabase project**. The frontend key is a
publishable/anon key intended for browser use. Never put a service-role key, an AI
provider key, or an encryption key in a `VITE_` variable: Vite includes those
values in browser code.

Generate a backend encryption key once. This command writes it directly to your
ignored `.env`, without displaying it, and refuses to replace an existing key:

```bash
.venv/bin/python - <<'PY'
import json
import re
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import dotenv_values

path = Path('backend/.env')
if dotenv_values(path).get('PROVIDER_KEYS_ENCRYPTION_KEYS'):
    raise SystemExit('Encryption is already configured; existing keys were preserved.')
text = path.read_text()
text = re.sub(r'^PROVIDER_KEYS_ENCRYPTION_KEYS=.*\n?', '', text, flags=re.MULTILINE)
keyring = json.dumps({'v1': Fernet.generate_key().decode()})
path.write_text(text.rstrip() + "\nPROVIDER_KEYS_ENCRYPTION_KEYS='" + keyring + "'\n")
path.chmod(0o600)
print('Encryption key saved locally. Keep a secure backup.')
PY
```

For a fresh setup, leave `PROVIDER_KEYS_ACTIVE_VERSION=v1`. Back up the encryption
key separately from the database: losing it makes saved provider keys unreadable.
Use the [rotation instructions](docs/provider-keys.md) for an existing installation;
do not generate a replacement just to troubleshoot a failed request.

Git ignores `.env`, `.env.local`, `.env.production`, and backup variants. Commit
only placeholder templates. Check that your files are ignored:

```bash
git check-ignore backend/.env frontend/.env
git diff --cached --name-only
```

The first command should list both files. Never use `git add -f` for credentials.
If a secret was previously committed, revoke or rotate it at its provider;
`.gitignore` does not erase Git history.

### 4. Start both servers

In terminal 1, from the repository root:

```bash
cd backend
../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start from `backend/` so the backend reads `backend/.env`.

In terminal 2, from the repository root:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Keep both terminals running. Open **http://localhost:5173**. The API documentation
is at **http://localhost:8000/docs**. Check that the backend responds:

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok"}
```

The health endpoint checks the process, not Supabase connectivity or provider
credentials. Restart the relevant server after changing its `.env` file.

### 5. Sign in and configure AI

Create an account in the app, confirm your email if required, and sign in. Open
**Settings → AI providers**, enter your own key, then select **Save** and **Test**.
The saved key is encrypted in Supabase; only its final four characters are shown.

| Feature | Required provider |
| --- | --- |
| Advisor chat | Saved OpenRouter key, otherwise a saved Gemini key |
| Statement parsing and background memory/recurring AI assistance | Gemini |
| Additional experimental financial-analysis mode | OpenRouter, required migrations, and `EVIDENCE_ADVISOR_ENABLED=true` |

An OpenRouter key works for ordinary chat without enabling experimental analysis.
Chat currently uses Gemini 2.5 Flash through OpenRouter. If you save both keys,
OpenRouter takes priority for chat. A failed OpenRouter request does not silently
switch to Gemini. The **Test** action checks authentication, not all model access
or quota limits. Provider usage may incur charges.

Start with a small statement you can verify, review the import preview before
saving, and follow [your first monthly review](#try-your-first-monthly-review).
Without AI keys, you can still use non-AI financial features with available data.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| API-key input boxes are disabled | Apply the credential-table migration, configure the backend encryption key, restart the backend, and refresh Settings. |
| Sign-in fails or no confirmation email arrives | Use the same Supabase project in both `.env` files; check email/password auth, confirmation requirements, and email delivery in Supabase. |
| Password-reset link opens the wrong page | Allow the exact `/reset-password` URL in Supabase Authentication URL Configuration. Keep the email template's Supabase confirmation link intact. |
| UI reports a network error | Confirm both servers are running; check `VITE_API_URL`, `FRONTEND_URL`, and the browser hostname. Restart after `.env` edits. |
| Missing table or column errors | Apply the outstanding migrations to the project named by `SUPABASE_URL`. |
| OpenRouter chat works but imports fail | Save and test a Gemini key; imports do not use the chat provider switch. |
| Provider authentication or quota error | Test the saved key, check model access and credit/quota at the provider, and replace revoked or leaked keys. |
| Node engine error during `npm ci` | Use Node 22.13+ within the 22.x series, then retry installation. |
| Port 5173 or 8000 is in use | Stop the old local server, or change the ports and update the matching environment/auth URLs. |

When reporting a problem, share the action, HTTP status, and sanitized error text.
Do not paste `.env` contents, authorization headers, API keys, or personal statements.

## For contributors

The stack is React/TypeScript, FastAPI/Python, Supabase, quantitative Python
engines, and configurable AI integrations. Start with the
[frontend](frontend/src), [finance engine](backend/app/engine),
[imports](backend/app/imports), and [advisor](backend/app/advisor).

| Check | Command |
| --- | --- |
| Backend, from `backend/` | `../.venv/bin/python -m pytest tests/ -q` |
| Offline portfolio/engine checks, from `backend/` | `../.venv/bin/python -m pytest tests/portfolio tests/evals/backend -q` |
| Frontend, from `frontend/` | `npm run build`, `npm run lint`, `npm run test:run` |
| Browser tests | [Setup and instructions](frontend/e2e/README.md) |

The full backend suite includes integration tests requiring a dedicated test
database. Mocked tests do not establish live model quality. Paid evaluations have
separate budget controls; see the offline guide before running them.

Python dependencies are defined in `pyproject.toml` and locked in `uv.lock`.
After dependency changes, run `uv lock`, then regenerate the compatibility file:

```bash
uv export --frozen --no-hashes --no-emit-project --output-file backend/requirements.txt
```

Do not edit the generated requirements file independently.

Before a release, run `python scripts/check_publication.py --ref HEAD` and review
[security guidance](SECURITY.md). For a repeatable bootstrap test without accessing
Supabase, install PostgreSQL with pgvector and run:

```bash
python scripts/verify_schema.py --pg-bin /path/to/postgresql/bin
```

The verifier creates an isolated temporary cluster with no TCP listener, applies
the schema, checks credential permissions and user isolation, verifies rollback
on a failed setup, then stops and removes the cluster. It uses minimal local
Supabase auth stubs; hosted authentication and email delivery still need a check
in your own Supabase project.
