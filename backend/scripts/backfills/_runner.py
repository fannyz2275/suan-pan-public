"""Discovery + idempotency framework for one-off data backfills.

Each backfill is a Python module under `backend/scripts/backfills/` whose
filename starts with an ISO date so they sort chronologically:

    backend/scripts/backfills/2026-05-01_seed_widget_owner.py

Every module must export:

    NAME: str          # unique key used in the applied_backfills table
    def apply(db, *, dry_run: bool) -> None: ...

`db` is the admin Supabase client. The runner records `NAME` in
`public.applied_backfills` after a successful run, so reruns are skipped.
Backfills should be **idempotent** anyway — the table is a belt-and-braces
guard, not the only line of defence.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
from dataclasses import dataclass
from typing import Callable, Protocol

from app.db import get_admin_db

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_[a-z0-9_]+$")


class _BackfillModule(Protocol):
    NAME: str
    apply: Callable[..., None]


@dataclass
class Backfill:
    name: str
    apply: Callable[..., None]


# Modules in scripts/backfills/ that are framework code, not backfills.
# `run` is the CLI entry point; it has no NAME/apply exports because it
# *invokes* discover(), it is not itself a backfill. Without this skip the
# discoverer raises on the CLI module itself the first time a real backfill
# is added (the prior test suite mocked iter_modules so never hit this).
_FRAMEWORK_MODULES = frozenset({"run"})


def discover() -> list[Backfill]:
    """Return all backfill modules sorted by NAME (which starts with a date)."""
    import scripts.backfills as pkg

    found: list[Backfill] = []
    for _, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg or modname.startswith("_") or modname in _FRAMEWORK_MODULES:
            continue
        mod = importlib.import_module(f"scripts.backfills.{modname}")
        name = getattr(mod, "NAME", None)
        apply = getattr(mod, "apply", None)
        if not name or not callable(apply):
            raise RuntimeError(
                f"Backfill module {modname} must export NAME (str) and apply(db, *, dry_run)"
            )
        if not _NAME_RE.match(name):
            raise RuntimeError(
                f"Backfill NAME {name!r} must match YYYY-MM-DD_lower_snake_slug"
            )
        found.append(Backfill(name=name, apply=apply))
    found.sort(key=lambda b: b.name)
    return found


def _applied_set(db) -> set[str]:
    rows = db.table("applied_backfills").select("name").execute().data or []
    return {r["name"] for r in rows}


def run(*, dry_run: bool, only: str | None) -> int:
    """Run pending backfills. Returns the number applied."""
    db = get_admin_db()
    backfills = discover()
    if only:
        backfills = [b for b in backfills if b.name == only]
        if not backfills:
            raise SystemExit(f"No backfill named {only!r}")
    applied = _applied_set(db)

    ran = 0
    for b in backfills:
        if b.name in applied and not only:
            logger.info("skip %s (already applied)", b.name)
            continue
        logger.info("apply %s%s", b.name, " (dry-run)" if dry_run else "")
        b.apply(db, dry_run=dry_run)
        if not dry_run:
            db.table("applied_backfills").upsert({"name": b.name}).execute()
        ran += 1
    return ran
