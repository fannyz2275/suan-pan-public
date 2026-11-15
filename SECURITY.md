# Security and private data

Do not post API keys, service-role tokens, personal statements, or financial
screenshots in public issues or pull requests. Report security problems through
a private channel agreed with the maintainer; share a minimal synthetic reproduction.

## Local configuration

Keep credentials in ignored `.env` files or your deployment's secret manager.
Frontend `VITE_` values are public browser configuration: use only the Supabase
publishable/anon key there. Provider keys are saved through authenticated Settings
and encrypted with a backend-only key. Back up that encryption key separately.

`EVAL_MOCKS=1` explicitly enables a test authentication bypass. Use it only in
isolated tests with synthetic data. Normal installations must use `EVAL_MOCKS=0`.

Run `python scripts/check_publication.py` before staging a release and
`python scripts/check_publication.py --ref HEAD` after committing. This heuristic
check covers common credential formats and private file paths, not every possible
secret or personal datum. Review fixtures and screenshots manually as well.

## Historical exposure

Some earlier commits contained provider credentials and private test artifacts.
Do not make the existing history public. Revoke/rotate exposed credentials at
the provider, update local/deployment secrets, and use a reviewed sanitized root
commit for publication, or separately coordinate a complete history cleanup.
Deleting a current file or adding an ignore rule does not remove old copies.
No claim is made that provider-side revocation has occurred until the operator
confirms it. Never test an exposed credential against live data just to see if it
still works.
