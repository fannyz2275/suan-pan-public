# Applying database migrations

For a **fresh** Supabase project, run the entire [`../schema.sql`](../schema.sql)
in the SQL Editor once. It includes every migration listed below inside a single
transaction. Do not run these files separately after fresh setup.

The files below are retained for **upgrading existing installations**. Apply only
those not already included in your database, in the listed order. Apply SQL
manually as the project operator; starting the backend does not run migrations.

| Order | File | Purpose |
| --- | --- | --- |
| 1 | [2026-05-10_security_country.sql](2026-05-10_security_country.sql) | Add `security_reference.country`. |
| 2 | [2026-05-10_security_price_misses.sql](2026-05-10_security_price_misses.sql) | Add the negative market-price cache. |
| 3 | [20261011_advisor_pending_analysis.sql](20261011_advisor_pending_analysis.sql) | Store pending experimental analyses and their resume state. |
| 4 | [20261011_transfer_counterparty_evidence.sql](20261011_transfer_counterparty_evidence.sql) | Add transfer counterparty evidence and ownership checks. |
| 5 | [20261012_user_provider_credentials.sql](20261012_user_provider_credentials.sql) | Store encrypted, per-user AI provider keys with backend-only access. |

For an existing project, apply only missing migrations. Keep a record for each
environment: these scripts are not all idempotent, and a local SQL file does not
prove it has been applied remotely. Do not rerun the base schema on an existing
database as an upgrade procedure.

After applying, verify the additions without retrieving credentials:

```sql
select country from public.security_reference limit 0;
select ticker, last_attempt_at, reason from public.security_price_misses limit 0;
select id from public.advisor_pending_analysis limit 0;
select counterparty_account_id, currency, counterparty_provenance
from public.transactions limit 0;
select provider, encryption_key_version from public.user_provider_credentials limit 0;
```

Saved provider keys also require backend encryption configuration. See
[local setup](../../../README.md#run-it-yourself) and
[provider-key configuration and rotation](../../../docs/provider-keys.md).

Market prices and security metadata use Yahoo Finance through `yfinance`; no
market-data API key is required. Unavailable prices remain explicitly unpriced.
