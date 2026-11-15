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
