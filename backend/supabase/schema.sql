-- Suan-Pan database schema (consolidated).
--
-- Apply once in Supabase SQL Editor on a fresh project. This file is the
-- single source of truth for the schema; previous incremental migrations
-- have been folded in. Do not run this on an existing installation.
-- For upgrades, apply only the outstanding files in migrations/.

begin;

-- ============================================================================
-- Extensions
-- ============================================================================
create extension if not exists "uuid-ossp";
create extension if not exists vector;


-- ============================================================================
-- Trigger functions
-- ============================================================================

-- Auto-create a profiles row when a new auth user is inserted.
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id) values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$ language plpgsql security definer;

-- Generic updated_at touch trigger.
create or replace function public.touch_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;


-- ============================================================================
-- profiles
-- ============================================================================
-- T1 identity. Dollar amounts deliberately do not live here — every dollar
-- figure the advisor sees comes from T2 (transactions / balances).
--
-- risk_tolerance / time_horizon: legacy text enums kept for the dual-read
-- window; risk_tolerance_v2 / time_horizon_v2 are the 1..5 scalars used by
-- the new context builder.
create table public.profiles (
    id uuid references auth.users(id) primary key,
    age integer,
    risk_tolerance text
        check (risk_tolerance in ('conservative', 'moderate', 'aggressive'))
        default 'moderate',
    risk_tolerance_v2 smallint
        check (risk_tolerance_v2 between 1 and 5),
    time_horizon text
        check (time_horizon in ('short','medium','long','unknown'))
        default 'unknown',
    time_horizon_v2 smallint
        check (time_horizon_v2 between 1 and 5),
    employment_status text
        check (employment_status in ('employed','self_employed','unemployed','retired','unknown'))
        default 'unknown',
    region text,
    dependents integer default 0,
    use_category_baselines boolean not null default true,
    notes_last_extracted_at timestamptz,
    notes_last_merged_at timestamptz,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_profiles_employment
    on public.profiles (employment_status)
    where employment_status is not null and employment_status <> 'unknown';

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
    before update on public.profiles
    for each row execute procedure public.touch_updated_at();

alter table public.profiles enable row level security;

create policy "profiles_own" on public.profiles
    using (auth.uid() = id);


-- ============================================================================
-- accounts
-- ============================================================================
create table public.accounts (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid references auth.users(id) not null,
    name text not null,
    nickname text,
    account_number_last4 text
        check (account_number_last4 is null or account_number_last4 ~ '^[0-9]{4}$'),
    type text
        check (type in ('checking','savings','brokerage','retirement','property','rsu','business','debt'))
        not null,
    balance numeric(15,2) default 0,
    source text check (source in ('manual','plaid')) default 'manual',
    plaid_account_id text,
    last_synced_at timestamptz,
    -- RSU / options
    vested_shares numeric,
    unvested_shares numeric,
    grant_price numeric(10,4),
    vesting_schedule jsonb,
    -- Property
    estimated_value numeric(15,2),
    purchase_price numeric(15,2),
    -- Business equity
    ownership_pct numeric(5,2),
    estimated_valuation numeric(15,2),
    liquidity_horizon_months integer,
    -- Debt: APR as decimal (0.2099 = 20.99%); NULL when unknown.
    apr numeric(6,4),
    -- Balance change tracking (rotated only when the value actually changes).
    balance_updated_at timestamptz,
    previous_balance numeric(15,2),
    previous_balance_at timestamptz,
    is_active boolean default true,
    created_at timestamptz default now()
);

alter table public.accounts enable row level security;

create policy "accounts_own" on public.accounts
    using (auth.uid() = user_id);


-- ============================================================================
-- account_balance_history
-- ============================================================================
-- T2 source of truth for net-worth-over-time. One row per (account, balance
-- change). Liquid accounts get dense history; illiquid (property, RSU,
-- business) get sparse history. NW(t) = sum of latest-balance-per-account
-- ≤ t for the user's active accounts.
create table public.account_balance_history (
    id uuid primary key default uuid_generate_v4(),
    account_id uuid not null references public.accounts(id) on delete cascade,
    user_id uuid not null references auth.users(id),
    balance numeric(15,2) not null,
    as_of timestamptz not null,
    source text not null
        check (source in ('initial','manual','plaid','file_import')),
    created_at timestamptz not null default now()
);

create index if not exists idx_abh_account_asof
    on public.account_balance_history (account_id, as_of desc);
create index if not exists idx_abh_user_asof
    on public.account_balance_history (user_id, as_of desc);

alter table public.account_balance_history enable row level security;

create policy abh_owner on public.account_balance_history
    for all using (auth.uid() = user_id);


-- ============================================================================
-- goals
-- ============================================================================
-- is_primary is a user-set flag — Overview UI shows a star toggle and the
-- advisor focuses analysis on these goals.
create table public.goals (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid references auth.users(id) not null,
    name text not null,
    type text
        check (type in ('savings','debt_payoff','investment','life_event'))
        not null,
    target_amount numeric(15,2) not null,
    target_date date not null,
    current_progress numeric(15,2) default 0,
    feasibility_score numeric(5,2),
    status text
        check (status in ('on_track','at_risk','off_track'))
        default 'on_track',
    notes text,
    is_active boolean default true,
    is_primary boolean not null default false,
    created_at timestamptz default now()
);

create index if not exists goals_user_primary_idx
    on public.goals (user_id)
    where is_primary;

alter table public.goals enable row level security;

create policy "goals_own" on public.goals
    using (auth.uid() = user_id);


-- ============================================================================
-- chat_sessions / chat_messages
-- ============================================================================
create table public.chat_sessions (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid references auth.users(id) not null,
    title text,
    snapshot_summary text,
    kind text default 'general'
        check (kind in ('general','findings_review')),
    created_at timestamptz default now()
);

create table public.chat_messages (
    id uuid default uuid_generate_v4() primary key,
    session_id uuid references public.chat_sessions(id) not null,
    role text check (role in ('user','assistant')) not null,
    content text not null,
    tool_context jsonb,
    created_at timestamptz default now()
);

alter table public.chat_sessions enable row level security;
alter table public.chat_messages enable row level security;

create policy "chat_sessions_own" on public.chat_sessions
    using (auth.uid() = user_id);

create policy "chat_messages_own" on public.chat_messages
    using (
        session_id in (
            select id from public.chat_sessions where user_id = auth.uid()
        )
    );


-- ============================================================================
-- transactions
-- ============================================================================
create table public.transactions (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid references auth.users(id) not null,
    account_id uuid references public.accounts(id) on delete set null,
    date date not null,
    description text not null,
    amount numeric(15,2) not null, -- negative = expense, positive = income
    category text
        check (category in ('income','food','transport','housing','utilities',
                            'healthcare','entertainment','shopping','transfer','other')),
    source text
        check (source in ('manual','plaid'))
        not null default 'manual',
    plaid_transaction_id text unique,
    transfer_group_id uuid,
    transfer_status text
        check (transfer_status in
            ('auto_paired','user_confirmed_internal','external','needs_review','dismissed')),
    created_at timestamptz default now()
);

create index if not exists transactions_transfer_group_idx
    on public.transactions (transfer_group_id)
    where transfer_group_id is not null;

create index if not exists transactions_transfer_status_idx
    on public.transactions (user_id, transfer_status)
    where transfer_status is not null;

alter table public.transactions enable row level security;

create policy "transactions_own" on public.transactions
    using (auth.uid() = user_id);


-- ============================================================================
-- plaid_items
-- ============================================================================
-- Service-role only; never exposed to authenticated clients.
create table public.plaid_items (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid references auth.users(id) not null,
    access_token text not null,
    item_id text not null,
    institution_name text,
    created_at timestamptz default now()
);

alter table public.plaid_items enable row level security;

create policy "plaid_items_service_only" on public.plaid_items
    using (false);


-- ============================================================================
-- recurring_rules / recurring_rule_matches
-- ============================================================================
create table public.recurring_rules (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid references auth.users(id) not null,
    keyword text not null,
    normalized_key_pattern text not null,
    amount_min numeric(15,2) not null,
    amount_max numeric(15,2) not null,
    amount_median numeric(15,2) not null,
    frequency text
        check (frequency in ('weekly','biweekly','semi_monthly','monthly',
                             'quarterly','semi_annual','annual'))
        not null,
    direction text check (direction in ('income','expense')) not null,
    confidence numeric(5,2) not null check (confidence >= 0 and confidence <= 1),
    status text
        check (status in ('proposed','pending_review','auto_applied',
                          'user_confirmed','user_rejected'))
        not null,
    source text
        check (source in ('heuristic','llm','user_created'))
        not null,
    last_seen_date date,
    next_expected_date date,
    occurrences_observed integer not null default 0,
    sample_transaction_ids uuid[] not null default '{}',
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique (user_id, normalized_key_pattern, frequency, direction)
);

create table public.recurring_rule_matches (
    rule_id uuid references public.recurring_rules(id) on delete cascade,
    transaction_id uuid references public.transactions(id) on delete cascade,
    matched_at timestamptz default now(),
    primary key (rule_id, transaction_id)
);

create index if not exists recurring_rules_user_status_idx
    on public.recurring_rules (user_id, status);
create index if not exists recurring_rules_user_direction_idx
    on public.recurring_rules (user_id, direction);
create index if not exists recurring_rule_matches_txn_idx
    on public.recurring_rule_matches (transaction_id);

alter table public.recurring_rules enable row level security;
alter table public.recurring_rule_matches enable row level security;

create policy "recurring_rules_own" on public.recurring_rules
    using (auth.uid() = user_id);

create policy "recurring_rule_matches_own" on public.recurring_rule_matches
    using (
        rule_id in (select id from public.recurring_rules where user_id = auth.uid())
    );


-- ============================================================================
-- user_notes  (Tier 3 retrieval substrate)
-- ============================================================================
-- Free-form facts / preferences / examples extracted from chat. Embedded for
-- semantic retrieval; importance + last_accessed_at drive Tier 1 ordering.
create table public.user_notes (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    kind text not null check (kind in ('fact','preference','example')),
    content text not null,
    tags text[] not null default '{}',
    entity_refs jsonb not null default '{}',
    embedding vector(768),
    source text not null
        check (source in ('chat_extraction','message_feedback','entity_edit','compaction_merge')),
    provenance jsonb not null default '{}',
    strength int not null default 1,
    importance smallint not null default 5
        check (importance between 1 and 10),
    last_accessed_at timestamptz not null default now(),
    supersedes uuid[] not null default '{}',
    superseded_by uuid,
    expires_at timestamptz,
    created_at timestamptz not null default now()
);

create index idx_user_notes_live
    on public.user_notes (user_id, kind, created_at desc)
    where superseded_by is null;

create index idx_user_notes_tags
    on public.user_notes using gin (tags);

create index idx_user_notes_embedding
    on public.user_notes using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

create unique index idx_user_notes_feedback_dedup
    on public.user_notes (user_id, (provenance->>'message_id'), (provenance->>'label'))
    where source = 'message_feedback'
        and superseded_by is null
        and expires_at is null;

create index idx_user_notes_identity_pool
    on public.user_notes (user_id, kind, importance desc, last_accessed_at desc)
    where superseded_by is null;

alter table public.user_notes enable row level security;

create policy "user_notes_select_own" on public.user_notes
    for select using (auth.uid() = user_id);


-- ============================================================================
-- user_engine_overrides  (procedural memory)
-- ============================================================================
-- Per-user behavioral overrides consulted by the engine at call time.
-- Writes happen service-side; readers are RLS-scoped.
create table public.user_engine_overrides (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    domain text not null
        check (domain in ('categorize','transfers','recurring','feasibility','baseline')),
    key text not null,
    value jsonb not null,
    source_note_id uuid references public.user_notes(id) on delete set null,
    strength smallint not null default 1,
    created_at timestamptz not null default now(),
    last_reinforced_at timestamptz not null default now(),
    retired_at timestamptz,
    unique (user_id, domain, key)
);

create index idx_overrides_user_domain
    on public.user_engine_overrides (user_id, domain)
    where retired_at is null;

alter table public.user_engine_overrides enable row level security;

create policy "overrides_select_own" on public.user_engine_overrides
    for select using (auth.uid() = user_id);


-- ============================================================================
-- tool_call_logs / user_tool_priors
-- ============================================================================
-- Episodic per-call log + nightly aggregation that reorders the tool list
-- shown to the LLM so each user's most-useful tools surface first.
create table public.tool_call_logs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    session_id uuid references public.chat_sessions(id) on delete set null,
    message_id uuid,
    tool_name text not null,
    args_hash text,
    ctx_signature text,
    succeeded boolean not null,
    duration_ms int,
    next_user_intent text,
    created_at timestamptz not null default now()
);

create index idx_tool_logs_agg
    on public.tool_call_logs (user_id, tool_name, ctx_signature, created_at desc);
create index idx_tool_logs_user_recent
    on public.tool_call_logs (user_id, created_at desc);

alter table public.tool_call_logs enable row level security;

create policy "tool_logs_select_own" on public.tool_call_logs
    for select using (auth.uid() = user_id);


create table public.user_tool_priors (
    user_id uuid not null references auth.users(id) on delete cascade,
    tool_name text not null,
    ctx_signature text not null,
    success_count int not null default 0,
    miss_count int not null default 0,
    utility_score real not null default 0,
    last_used_at timestamptz,
    primary key (user_id, tool_name, ctx_signature)
);

create index idx_tool_priors_user_utility
    on public.user_tool_priors (user_id, utility_score desc);

alter table public.user_tool_priors enable row level security;

create policy "tool_priors_select_own" on public.user_tool_priors
    for select using (auth.uid() = user_id);


-- ============================================================================
-- applied_backfills
-- ============================================================================
-- Tracks which one-off Python data-backfill scripts have been applied.
-- DDL still goes through this file; this table is for *data* backfills.
create table public.applied_backfills (
    name text primary key,
    applied_at timestamptz not null default now()
);


-- ============================================================================
-- Portfolio: securities + snapshots + holdings + investment txns + prices
-- ============================================================================

-- One row per ticker we've ever encountered. Enriched via yfinance.
create table public.security_reference (
    id uuid default uuid_generate_v4() primary key,
    ticker text unique not null,
    name text,
    security_type text,
    asset_class text,
    sector text,
    region text,
    look_through jsonb,
    enriched_at timestamptz,
    enrichment_source text
);

-- Real holdings observations.
create table public.portfolio_snapshots (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid references auth.users(id) not null,
    account_id uuid references public.accounts(id) on delete cascade not null,
    snapshot_date date not null,
    source text check (source in ('plaid','statement_import','manual')) not null,
    total_value numeric(15,2) not null,
    cash_value numeric(15,2) default 0,
    superseded_at timestamptz,
    created_at timestamptz default now(),
    unique (account_id, snapshot_date, source)
);

create index portfolio_snapshots_user_date_idx
    on public.portfolio_snapshots (user_id, snapshot_date desc)
    where superseded_at is null;

-- Normalized holdings — one row per ticker per snapshot.
create table public.snapshot_holdings (
    id uuid default uuid_generate_v4() primary key,
    snapshot_id uuid references public.portfolio_snapshots(id) on delete cascade not null,
    ticker text not null,
    security_id uuid references public.security_reference(id),
    quantity numeric(20,8) not null,
    price numeric(15,4) not null,
    market_value numeric(15,2) not null,
    cost_basis numeric(15,2),
    unrealized_gain numeric(15,2)
);

create index snapshot_holdings_ticker_idx
    on public.snapshot_holdings (ticker);

-- Investment transactions. amount is signed (positive = cash in,
-- negative = cash out). reinvest is recorded with amount=0.
create table public.investment_transactions (
    id uuid default uuid_generate_v4() primary key,
    user_id uuid references auth.users(id) not null,
    account_id uuid references public.accounts(id) on delete cascade not null,
    date date not null,
    type text check (type in (
        'buy','sell','dividend','interest','fee',
        'transfer_in','transfer_out','split','reinvest'
    )) not null,
    ticker text,
    security_id uuid references public.security_reference(id),
    quantity numeric(20,8),
    price numeric(15,4),
    amount numeric(15,2) not null,
    source text check (source in ('plaid','statement_import','manual')) not null,
    plaid_investment_transaction_id text unique,
    created_at timestamptz default now()
);

create index investment_txns_user_date_idx
    on public.investment_transactions (user_id, date desc);

-- Daily close cache.
create table public.security_prices (
    ticker text not null,
    date date not null,
    close numeric(15,4) not null,
    primary key (ticker, date)
);

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

-- Reference + price tables are read-mostly and shared across users;
-- writes go through the service role only.
create policy "security_reference_read_all" on public.security_reference
    for select using (true);

create policy "security_prices_read_all" on public.security_prices
    for select using (true);


-- ============================================================================
-- RPCs
-- ============================================================================

-- Tier 3 candidate retrieval — full rows + cosine similarity in one trip
-- so the Python side can do MMR + per-pool min-max normalization.
create or replace function public.match_user_notes_scored(
    p_user_id uuid,
    p_query vector(768),
    p_limit int default 20
)
returns table (
    id uuid,
    user_id uuid,
    kind text,
    content text,
    tags text[],
    entity_refs jsonb,
    embedding vector(768),
    source text,
    provenance jsonb,
    strength int,
    importance smallint,
    last_accessed_at timestamptz,
    supersedes uuid[],
    superseded_by uuid,
    expires_at timestamptz,
    created_at timestamptz,
    cosine_similarity float
)
language sql
stable
as $$
    select
        n.id, n.user_id, n.kind, n.content, n.tags, n.entity_refs, n.embedding,
        n.source, n.provenance, n.strength, n.importance, n.last_accessed_at,
        n.supersedes, n.superseded_by, n.expires_at, n.created_at,
        1 - (n.embedding <=> p_query) as cosine_similarity
    from public.user_notes n
    where n.user_id = p_user_id
        and n.embedding is not null
        and n.superseded_by is null
        and (n.expires_at is null or n.expires_at > now())
    order by n.embedding <=> p_query asc
    limit p_limit;
$$;

-- Single-kind similarity search with absolute threshold (legacy retriever).
create or replace function public.match_user_notes(
    p_user_id uuid,
    p_query vector(768),
    p_kind text,
    p_limit int default 8,
    p_threshold float default 0.7
)
returns table (
    id uuid,
    content text,
    tags text[],
    entity_refs jsonb,
    source text,
    provenance jsonb,
    strength int,
    similarity float
)
language sql
stable
as $$
    select
        n.id, n.content, n.tags, n.entity_refs, n.source, n.provenance, n.strength,
        1 - (n.embedding <=> p_query) as similarity
    from public.user_notes n
    where n.user_id = p_user_id
        and n.kind = p_kind
        and n.embedding is not null
        and n.superseded_by is null
        and (n.expires_at is null or n.expires_at > now())
        and 1 - (n.embedding <=> p_query) >= p_threshold
    order by n.embedding <=> p_query asc
    limit p_limit;
$$;

-- Users with chat activity since their last extraction tick.
create or replace function public.notes_eligible_users_for_extraction(p_idle_cutoff timestamptz)
returns table (user_id uuid)
language sql
stable
as $$
    with last_msg as (
        select s.user_id::uuid as user_id, max(m.created_at) as last_msg_at
        from public.chat_sessions s
        join public.chat_messages m on m.session_id = s.id
        group by s.user_id
    )
    select lm.user_id
    from last_msg lm
    join public.profiles p on p.id = lm.user_id
    where lm.last_msg_at < p_idle_cutoff
        and (p.notes_last_extracted_at is null or lm.last_msg_at > p.notes_last_extracted_at);
$$;

-- Public-schema wrappers around pg_advisory_lock builtins so PostgREST can
-- call them via .rpc(...). Without these, the extraction tick() loop cannot
-- acquire per-user locks.
create or replace function public.notes_try_advisory_lock(p_key bigint)
returns boolean
language sql
volatile
as $$
    select pg_try_advisory_lock(p_key);
$$;

create or replace function public.notes_advisory_unlock(p_key bigint)
returns boolean
language sql
volatile
as $$
    select pg_advisory_unlock(p_key);
$$;


-- ============================================================================
-- Included migration: 2026-05-10_security_country.sql
-- ============================================================================
-- Capture the raw country (not just the bucketed region) on
-- security_reference so the new "by-country" exposure dimension can group on
-- the actual ISO-style country name instead of the four-bucket region.

alter table public.security_reference
    add column if not exists country text;


-- ============================================================================
-- Included migration: 2026-05-10_security_price_misses.sql
-- ============================================================================
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


-- ============================================================================
-- Included migration: 20261011_advisor_pending_analysis.sql
-- ============================================================================
create table if not exists public.advisor_pending_analysis (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id),
    session_id uuid not null references public.chat_sessions(id) on delete cascade,
    question text not null,
    month text not null check (month ~ '^\d{4}-\d{2}$'),
    requirements jsonb not null,
    data_version text not null,
    status text not null default 'waiting' check (status in ('waiting','running','complete','failed')),
    result jsonb,
    created_at timestamptz not null default now()
);
alter table public.advisor_pending_analysis enable row level security;
create policy pending_analysis_owner on public.advisor_pending_analysis
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create index if not exists pending_analysis_session on public.advisor_pending_analysis(user_id, session_id, created_at desc);

-- Claim is an atomic compare-and-swap. The service route has already checked ownership.
create or replace function public.claim_pending_analysis(p_id uuid, p_user_id uuid)
returns setof public.advisor_pending_analysis language sql security invoker set search_path = public as $$
    update public.advisor_pending_analysis set status = 'running'
    where id = p_id and user_id = p_user_id and status = 'waiting'
    returning *;
$$;
revoke all on function public.claim_pending_analysis(uuid, uuid) from public, anon, authenticated;
grant execute on function public.claim_pending_analysis(uuid, uuid) to service_role;


-- ============================================================================
-- Included migration: 20261011_transfer_counterparty_evidence.sql
-- ============================================================================
-- Nullable evidence: absent identity never implies reciprocal verification.
alter table public.transactions
    add column if not exists counterparty_account_id uuid references public.accounts(id) on delete set null,
    add column if not exists currency text check (currency ~ '^[A-Z]{3}$'),
    add column if not exists counterparty_provenance text
        check (counterparty_provenance in ('user_confirmed', 'provider_verified'));

create or replace function public.check_transfer_counterparty_owner()
returns trigger language plpgsql set search_path = public as $$
begin
    if new.counterparty_account_id is not null and not exists (
        select 1 from public.accounts a
        where a.id = new.counterparty_account_id and a.user_id = new.user_id
    ) then
        raise exception 'Counterparty account must belong to transaction owner';
    end if;
    return new;
end;
$$;
drop trigger if exists transactions_counterparty_owner on public.transactions;
create trigger transactions_counterparty_owner before insert or update
on public.transactions for each row execute function public.check_transfer_counterparty_owner();


-- ============================================================================
-- Included migration: 20261012_user_provider_credentials.sql
-- ============================================================================
-- Backend-only encrypted credentials. Apply in the Supabase SQL Editor.
create table if not exists public.user_provider_credentials (
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('gemini', 'openrouter')),
  ciphertext text not null,
  encryption_key_version text not null,
  last_four text not null,
  revision uuid not null,
  validation_status text not null default 'untested' check (validation_status in ('untested','valid','failed')),
  validated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, provider)
);
alter table public.user_provider_credentials enable row level security;
revoke all on public.user_provider_credentials from public, anon, authenticated;
grant select, insert, update, delete on public.user_provider_credentials to service_role;

commit;
