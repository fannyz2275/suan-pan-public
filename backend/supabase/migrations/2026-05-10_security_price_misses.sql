-- Negative price-lookup cache.
--
-- yfinance retries (and fails) on every page load for delisted or otherwise
-- unfetchable tickers, blocking the timeseries endpoint by 5-10 seconds per
-- request. This table records each failed attempt so subsequent requests can
-- skip the network round-trip until the entry expires (default 7 days).

create table if not exists public.security_price_misses (
    ticker text primary key,
    last_attempt_at timestamptz not null default now(),
    reason text
);

alter table public.security_price_misses enable row level security;

drop policy if exists "security_price_misses_read_all" on public.security_price_misses;
create policy "security_price_misses_read_all" on public.security_price_misses
    for select using (true);
