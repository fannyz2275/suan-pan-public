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
