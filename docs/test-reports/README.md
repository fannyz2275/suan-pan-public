# Test reports

Commit only reports produced with synthetic fixtures. Historical live-account
screenshots and associated exploratory reports have been removed from the release
contents because they included personal financial information. They are not
appropriate public examples, even when a test passed.

Useful reproducible checks:

- `frontend/e2e/forecast-plans.spec.ts`: synthetic financial-plan scenarios.
- `frontend/e2e/provider-keys.spec.ts`: synthetic credential lifecycle checks.
- `backend/tests/test_publication_safety.py`: authorization and publication guards.
- `python scripts/check_publication.py`: scan current tracked release contents.
- `python scripts/verify_schema.py --pg-bin /path/to/postgresql/bin`: isolated SQL bootstrap checks; PostgreSQL with pgvector required.

Do not commit browser screenshots from a signed-in personal account. Sanitize
report text, logs, prompts, and response bodies as well as images. Store private
investigation artifacts outside the repository or in an ignored local directory.
