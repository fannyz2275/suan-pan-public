# Publication hardening verification

## Completed

- Removed 11 personal artifacts from release contents; retained only in an ignored, owner-only local archive.
- Removed personal Supabase project defaults from source configuration.
- Added a publication-content scanner and a CI job for common credential patterns, service-role tokens, private environment files, and report screenshots.
- Added an explicit conversation ownership check before chat reads context or messages. Cross-user/missing-session regressions reproduced the issue before the fix and pass afterward.
- Changed the example to `EVAL_MOCKS=0`; verified evaluation headers cannot authenticate in normal mode.
- Executed the complete bootstrap on disposable PostgreSQL 18 with pgvector. Verified profile creation, credential-table permissions/RLS, session isolation, and atomic rollback after an injected failure. No production database was queried or modified.

## Results

- Backend: 1,180 passed, 20 skipped, 13 deselected; 28 snapshots passed.
- Frontend: 153 passed; lint and production build passed (existing bundle-size warning).
- SQL verifier: passed; temporary server stopped automatically.
- Whitespace and current publication-content checks: passed.

## Operator actions still required

Provider revocation cannot be verified from source code. Rotate the previously
exposed Supabase service-role credential and revoke the old Google key, then
update local/deployment configuration. Do not publish the original Git history.
Use the separately prepared clean-root release branch in a new repository, or
coordinate a reviewed remote history rewrite. Publishing a branch in the old
repository does not remove other branches, tags, pull requests, or old objects.

The local SQL verifier supplies minimal Supabase auth stubs. It validates the
schema and database behavior, not hosted signup/email delivery. Review and test
hosted auth separately before offering a shared deployment.
