# Data backfills

One-off Python scripts that reshape data after a deploy when SQL alone isn't
enough — typically because the new shape is computed from existing data using
the same engine code production runs.

## When to write a backfill (vs. SQL migration)

| Situation | Tool |
|---|---|
| Add/drop column, change type, change index | SQL migration in `backend/supabase/migrations/` |
| Static `update ... set` over rows | SQL migration |
| Need to call Python (engine derivations, parsers, normalisers) | Backfill script here |

If both: ship the SQL migration first, then a backfill script that runs the
Python part.

## Adding one

1. Create `backend/scripts/backfills/YYYY-MM-DD_short_slug.py`.
2. Export:
   ```python
   NAME = "YYYY-MM-DD_short_slug"  # must match the filename

   def apply(db, *, dry_run: bool) -> None:
       ...
   ```
3. Make it idempotent. The runner records `NAME` in `applied_backfills` after
   success and skips on subsequent runs, but the script should be safe to
   rerun even if that table is dropped.
4. Test locally with `--dry-run` before the real run.

## Running

```bash
cd backend
python -m scripts.backfills.run --dry-run     # see what would change
python -m scripts.backfills.run               # apply pending
python -m scripts.backfills.run --only 2026-05-01_my_backfill  # retry one
```

In CI, this is invoked from the `Post-deploy` workflow with
`workflow_dispatch` (manual trigger). Don't auto-run on every push — backfills
touch user data and a bad commit shouldn't have an automatic shot at it.
