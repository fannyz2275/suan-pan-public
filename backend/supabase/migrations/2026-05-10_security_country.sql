-- Capture the raw country (not just the bucketed region) on
-- security_reference so the new "by-country" exposure dimension can group on
-- the actual ISO-style country name instead of the four-bucket region.

alter table public.security_reference
    add column if not exists country text;
