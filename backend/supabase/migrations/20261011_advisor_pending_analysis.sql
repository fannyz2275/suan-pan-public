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
