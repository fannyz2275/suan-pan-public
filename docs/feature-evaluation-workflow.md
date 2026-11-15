# Evaluation workflow

Use deterministic tests for financial calculations and API behavior, frontend
checks for interactions, and separate advisor evaluations for response quality.
A passing mocked test does not establish live model quality or hosted database
correctness.

## Local checks

Install the locked Python environment with `uv sync --locked` at the repository
root. From `backend/`, run:

```bash
../.venv/bin/python -m pytest tests/portfolio tests/evals/backend -q
../.venv/bin/python -m pytest tests/evals/chat -q
```

From `frontend/`, run:

```bash
npm run lint
npm run build
npm run test:run
```

See [browser-test setup](../frontend/e2e/README.md) for synthetic user journeys.
The [CI workflow](../.github/workflows/checks.yml) defines the automated PR checks.
The full backend suite also contains tests that require a dedicated Supabase test
project; review fixtures before running integration tests.

## Advisor experiments

Read the [offline advisor guide](../backend/tests/evals/chat/OFFLINE.md) before
running evaluation campaigns. Distinguish deterministic harness tests from live
provider calls. Record the code, fixtures, model configuration, scoring rules,
cost limits, and infrastructure errors with each comparison. Do not use personal
financial records or production databases as evaluation fixtures.

Memory updates provide context; they do not retrain the model. Improvement on
unseen questions has not been established. Automated memory comparison and
promotion are not implemented release gates.

Publish only synthetic or sanitized evidence; follow the
[test-report guidance](test-reports/README.md) and [security guidance](../SECURITY.md).
