# Saved, encrypted AI provider keys

## Agreed intent

Users supply their own provider credentials through Settings. Credentials persist
across sign-ins, encrypted on the backend, so the app does not depend on a shared
leaked key. The user selected saved encrypted keys over session-only storage.
Existing financial records and forecast behavior remain unchanged.

## Scope and user experience

Add an AI providers section to existing Dashboard Settings with separate Gemini
and OpenRouter cards. Each card has a masked write-only input, Save/Replace,
Test saved key, and Remove. Show configured status, last four characters, saved
 time, and last validation result; never return the full saved key. Clear the
input immediately after successful saving. Explain that provider usage is billed
to the user's provider account and which features use each credential.

Gemini supports current chat, statement parsing, recurring tie-breaking, and
memory features. OpenRouter supports the existing evidence-first analysis when
that deployment feature is enabled. This change does not make provider APIs
interchangeable, add arbitrary endpoints, or add a model picker. Disabled
OpenRouter features remain visibly marked unavailable in this deployment.

Missing/invalid credentials produce a concise message linking to Settings.
Quantitative forecasts and browsing imported records remain available. Optional
LLM assistance uses existing deterministic fallbacks when credentials are absent;
required model operations fail clearly. A failed lookup or decryption must never
silently fall back to an environment credential.

## Storage and encryption

Create `user_provider_credentials` in a dated Supabase migration with primary key
(user_id, provider), foreign key to auth.users with cascade deletion, ciphertext,
encryption_key_version, last_four, created_at, updated_at, and sanitized validation
metadata. Provider is constrained to gemini or openrouter. Enable RLS, deny direct
anon/authenticated access, and permit backend service-role access only. Every
backend query explicitly filters the authenticated user ID and provider; user ID
is never accepted from request bodies.

Use the cryptography library's authenticated Fernet encryption. The encrypted
payload includes version, user ID, provider, and key. On decryption validate the
embedded user/provider binding to reject ciphertext copied between users or
providers. Encryption keys are separate backend-only environment secrets;
`PROVIDER_KEYS_ENCRYPTION_KEYS` contains a version-to-key JSON map and
`PROVIDER_KEYS_ACTIVE_VERSION` selects new writes. Never generate an ephemeral
master key at process startup or derive one from a Supabase/API credential.

Missing/invalid encryption configuration disables credential operations with a
sanitized 503 response. Existing unrelated API features still start. Rotation
retains old decryption keys while an operator command re-encrypts rows under the
new active version; do not log plaintext or ciphertext. Document recovery and
backup implications: loss of encryption keys requires users to re-enter provider
keys. No real master key belongs in examples, fixtures, Git, or frontend env vars.

## API and credential resolution

Authenticated `/profile/ai-providers` routes:

- GET: supported providers and metadata/configuration state only.
- PUT /{provider}: validate bounded secret input and encrypt/upsert atomically.
  Saving does not implicitly call a provider.
- POST /{provider}/test: validate the saved credential with a fixed, allowlisted
  provider endpoint and bounded timeout. Send no financial data. A successful
  authentication probe is not a promise of model entitlement or quota.
- DELETE /{provider}: idempotently delete only that user's provider credential.

Use SecretStr/repr exclusion and sanitized validation responses. Pydantic/FastAPI
validation must not echo secret request bodies. Never include upstream response
bodies, auth headers, keys, or ciphertext in error responses or logs. Reject
unknown fields, provider names, excessive lengths, empty values, and control
characters. Metadata responses and writes use Cache-Control: no-store.

Centralize resolution in a backend `provider_credentials` module. Resolve keys
from the authenticated user, or an explicit user ID supplied by a trusted
background job. Pass a request/job-scoped client into existing parsing/advisor
helpers. Do not mutate global settings, share a user's client on app.state, or
store credentials in localStorage, sessionStorage, chat records, notes, prompts,
MCP tool payloads, or telemetry. Avoid a cross-request plaintext key cache.
Close scoped clients when requests/jobs finish.

Replace direct environment-key construction across advisor chat/context,
OpenRouter analysis/resume, import preview, portfolio statement parsing, recurring
LLM refinement, engine LLM routes, entity-edit note capture, and idle extraction/
preference merging. Audit MCP-triggered AI paths as well; resolve within the
trusted user scope rather than allowing the model to choose a credential owner.
The server-wide Gemini client must no longer perform user-specific work.
Environment keys are not a fallback for these user-facing paths.

Key replacement/removal applies to subsequent operations. Requests already sent
to a provider cannot be recalled; no new background calls should begin with a
removed key. Validation writes must be conditional on the credential version so
an old test result cannot mark a replacement key valid. Never auto-retry paid
calls merely because a key changed.

## Verification

Backend tests must demonstrate encryption at rest, tamper/wrong-user/wrong-provider
rejection, missing master-key behavior, rotation, replacement, deletion, and
strict cross-user isolation. Route tests cover unauthenticated calls, rejected
providers, validation errors without secret echoes, metadata-only reads, and
sanitized upstream failures. Concurrency tests cover replacement during testing.

Integration tests exercise each actual AI call path with two users and fake
provider transports, proving which credential reaches each transport and that
no credential is included in prompts/tool payloads. Background jobs must resolve
separately for each user, including missing-key and deletion cases.

Playwright checks at desktop/mobile cover save, masked status, replace, test
success/failure, remove, reload persistence, disabled provider capabilities,
unconfigured encryption state, and missing-key links from chat/import. Use
synthetic secrets and a real local encrypted credential service with in-memory
records. Mock only external authentication/database/provider boundaries. Do not
use real user keys or paid calls as test fixtures.

Run affected backend tests, frontend tests/build/lint, then the existing financial
plan browser suite to ensure provider settings do not disrupt financial views.
Inspect diffs and errors for accidental credentials before any commit.

## Deployment and acceptance

Document the backend-only encryption variables and master-key generation through
a local secret-safe command. The repository requires the user to apply the dated
SQL migration in Supabase SQL Editor before live database testing. Do not write
real provider or encryption keys into committed files. Local synthetic verification
can run before migration; report live persistence separately.

Acceptance: a signed-in user can save an encrypted credential once, use its
existing provider-backed features after reload/restart, replace/remove it, and
receive actionable errors. No other user can read or use that credential. Existing
forecast calculations continue working without any configured AI credential.

This feature does not revoke the leaked Google key or erase Git history. Those
remain separate incident-remediation actions.
