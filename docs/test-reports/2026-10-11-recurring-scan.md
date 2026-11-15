# Recurring scan repair

## Scope and findings

- Mixed new/existing rule upserts omitted `id` on new rows. Bulk rows now have
  uniform keys, and newly saved rules have IDs in the scan response.
- Rediscovered pending/proposed rules lost their persisted identity and could
  violate the unique user/pattern/frequency/direction constraint. Detection now
  reuses that identity and avoids overriding active or rejected rules.
- Removed the explanatory paragraph, renamed the section to Recurring payments,
  and clarified the last-payment date filter.
- Failed requests no longer claim the server's saved rules are unchanged.

The regression tests failed before the fix and passed afterward. The original
live request's server error was not accessible, so these confirmed code defects
are not proof of which failure occurred in that specific request. No live scan
or financial data mutation was performed for verification.

## Verification

- Recurring backend suite and routes: 87 passed.
- Full backend suite: 1123 passed, 20 skipped, 13 setup errors (Supabase DNS).
- Frontend unit suite: 150 passed.
- Production build: passed; existing large-bundle warning remains.
- Desktop/mobile Playwright: 2 passed with mocked APIs and installed Chrome.
  Default Playwright browser was absent; sandboxed Chrome launch was blocked.
  The successful run used an isolated browser profile outside the sandbox.
- Changed frontend files: ESLint passed.
- Full frontend lint: existing `react-hooks/set-state-in-effect` error at
  `frontend/src/components/TransferReviewBadge.tsx:15`.
- `git diff --check`: passed before final commit.

### Supabase-dependent setup errors

All failed with `httpx.ConnectError` during fixture setup:

- `tests/notes/test_capture_integration.py::test_account_rename_creates_fact_note`
- `tests/notes/test_compaction.py::test_prune_examples_caps_at_per_tag_limit`
- `tests/notes/test_retrieval.py::test_retrieve_notes_filters_facts_by_scope_tags`
- `tests/notes/test_retrieval.py::test_retrieve_notes_always_injects_high_strength_preferences`
- `tests/notes/test_retrieval.py::test_retrieve_notes_excludes_superseded_and_expired`
- `tests/notes/test_router.py::test_post_feedback_creates_example_notes`
- `tests/notes/test_router.py::test_get_notes_returns_users_live_notes_when_flag_enabled`
- `tests/notes/test_router.py::test_get_notes_404_when_flag_disabled`
- `tests/notes/test_router.py::test_post_extract_now_runs_extractor`
- `tests/notes/test_store.py::test_insert_note_round_trip`
- `tests/notes/test_store.py::test_retire_note_sets_expires_at`
- `tests/notes/test_store.py::test_supersede_marks_old_rows`
- `tests/notes/test_store.py::test_similarity_search_returns_closest_first`
