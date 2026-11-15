\set ON_ERROR_STOP on
-- Check bootstrap structure and credential access without real users or keys.
do $$
begin
  if to_regclass('public.user_provider_credentials') is null then raise exception 'Credential table missing'; end if;
  if to_regclass('public.advisor_pending_analysis') is null then raise exception 'Pending analysis table missing'; end if;
  if to_regclass('public.security_price_misses') is null then raise exception 'Price cache missing'; end if;
  if not (select relrowsecurity from pg_class where oid='public.user_provider_credentials'::regclass) then raise exception 'Credential RLS disabled'; end if;
  if has_table_privilege('authenticated', 'public.user_provider_credentials','SELECT') or
     has_table_privilege('anon','public.user_provider_credentials','SELECT') then raise exception 'Browser can read credentials'; end if;
  if not has_table_privilege('service_role','public.user_provider_credentials','INSERT') then raise exception 'Backend cannot save credentials'; end if;
end $$;
begin;
insert into auth.users values ('00000000-0000-4000-8000-000000000001'), ('00000000-0000-4000-8000-000000000002');
do $$
begin
 if (select count(*) from public.profiles) <> 2 then raise exception 'Profile trigger failed'; end if;
end $$;
-- All test rows are rolled back; no production connection is used.
insert into public.chat_sessions (id,user_id) values
 ('00000000-0000-4000-8000-000000000011','00000000-0000-4000-8000-000000000001'),
 ('00000000-0000-4000-8000-000000000012','00000000-0000-4000-8000-000000000002');
grant select on public.chat_sessions to authenticated;
set local role authenticated;
set local request.jwt.claim.sub = '00000000-0000-4000-8000-000000000001';
do $$
begin
 if (select count(*) from public.chat_sessions) <> 1 then raise exception 'Session RLS isolation failed'; end if;
end $$;
rollback;
select 'Bootstrap structure, profile trigger, credential permissions, and session RLS passed' as result;
