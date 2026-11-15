# Saved AI provider keys

Users manage Gemini and OpenRouter keys in **Settings → AI providers**. Keys are write-only, encrypted by the backend, and scoped to the authenticated user. The UI displays only the final four characters and validation metadata. Testing a key sends an authentication probe with no financial data; success does not guarantee access to every model or sufficient quota. Advisor chat automatically prefers a saved OpenRouter key and otherwise uses a saved Gemini key. It uses Gemini 2.5 Flash through OpenRouter with the existing financial-tool loop. The additional evidence-analysis mode remains subject to its deployment feature flag. Statement imports and background AI features still require Gemini. A failing saved OpenRouter key produces an error rather than silently switching providers.

## Deployment

1. Apply `backend/supabase/migrations/20261012_user_provider_credentials.sql` in the Supabase SQL Editor. This must be done by the operator before live persistence testing. The table is accessible only through the backend service role.
2. Generate a Fernet key using Python's `cryptography.fernet.Fernet.generate_key()`. Store it in your backend secret manager; never put it in frontend configuration or commit it.
3. Configure `PROVIDER_KEYS_ENCRYPTION_KEYS` as a JSON object mapping versions to generated keys, for example `{"v1":"<generated Fernet key>"}`, and `PROVIDER_KEYS_ACTIVE_VERSION=v1`. For local development, use the ignored `backend/.env` and single-quote the JSON value.
4. Restart the backend. Open Settings, save a replacement provider key, and test it. Revoke any previously exposed provider key at the provider; deleting it locally does not revoke it or erase Git history.

User-facing AI operations do not fall back to shared `GOOGLE_API_KEY` or `OPENROUTER_API_KEY` environment values. Non-AI financial features remain available when credential storage is unconfigured. Background extraction skips users without usable saved Gemini credentials. Requests already in flight can finish after removal, but the next provider call checks the current saved credential.

## Encryption-key rotation and recovery

Back up encryption keys separately from the database. Losing them makes saved credentials unreadable; users must replace their provider keys if recovery is impossible. Database backups alone cannot recover credentials.

Add a new version to the key map while retaining all old versions, set it active, and restart all backend workers with the expanded map. From `backend/`, run `../.venv/bin/python -m app.provider_credentials.rotate`. The command re-encrypts rows with their user/provider binding and preserves validation metadata. Concurrent replacement is protected by revision checks. Rerun and verify no rows retain old versions before removing an old key from active deployments. Retain old keys securely for any backups that still require them. Do not log key values or database ciphertext during verification.

## Verification

`backend/tests/test_provider_credentials.py` covers encryption, isolation, rotation, request/job ownership, replacement/deletion, sanitized errors, and retry behavior. The Playwright provider suite uses real credential routes and encryption with synthetic storage and fake provider transports. It does not validate a live Supabase migration or spend provider credits.
