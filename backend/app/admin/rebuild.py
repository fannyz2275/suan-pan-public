"""Rebuild derived data across users.

Backfills (`scripts/backfills/`) cover *one-shot* reshaping after a schema
change. This module covers the other case: when a logic fix means the
*current* derived values produced from current source data are now wrong
and we want to recompute them.

Each step here is idempotent — running rebuild against an unchanged
codebase should be a no-op. Add new steps as new derivations land.

Usage:

    cd backend
    python -m app.admin.rebuild --dry-run
    python -m app.admin.rebuild
    python -m app.admin.rebuild --user-id <uuid>
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Callable

from app.db import get_admin_db
from app.engine.transfers import safe_scan_transfers_for_user

logger = logging.getLogger(__name__)


@dataclass
class RebuildStep:
    name: str
    run: Callable[[object, str], None]  # (db, user_id) -> None


def _step_rescan_transfers(db, user_id: str) -> None:
    safe_scan_transfers_for_user(db, user_id)


# Ordered list of steps. New rebuild steps get appended here as the engine
# grows; nothing depends on order today, but keeping the list explicit makes
# it obvious what runs.
STEPS: list[RebuildStep] = [
    RebuildStep(name="rescan_transfers", run=_step_rescan_transfers),
]


def _list_user_ids(db, scope: str | None) -> list[str]:
    if scope:
        return [scope]
    rows = db.table("profiles").select("id").execute().data or []
    return [r["id"] for r in rows]


def rebuild(*, user_id: str | None, dry_run: bool) -> dict:
    db = get_admin_db()
    user_ids = _list_user_ids(db, user_id)
    summary = {"users": len(user_ids), "steps": len(STEPS), "errors": 0}
    for uid in user_ids:
        for step in STEPS:
            label = f"{step.name} user={uid}"
            if dry_run:
                logger.info("would run %s", label)
                continue
            try:
                logger.info("run %s", label)
                step.run(db, uid)
            except Exception:
                # Don't abort the whole rebuild on one user's failure — log
                # and continue so the rest still get the fix. The summary
                # surfaces the error count to the caller.
                logger.exception("failed %s", label)
                summary["errors"] += 1
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-derive engine outputs across users.")
    parser.add_argument("--user-id", help="Run for a single user only.")
    parser.add_argument("--dry-run", action="store_true", help="Log what would run without writing.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    summary = rebuild(user_id=args.user_id, dry_run=args.dry_run)
    print(
        f"Rebuild complete — users={summary['users']} steps={summary['steps']} errors={summary['errors']}"
    )
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
