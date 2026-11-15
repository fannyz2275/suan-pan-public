"""CLI entrypoint: `python -m scripts.backfills.run [--dry-run] [--only NAME]`.

Run from the `backend/` directory so `app.*` and `scripts.*` resolve:

    cd backend
    python -m scripts.backfills.run --dry-run
    python -m scripts.backfills.run
    python -m scripts.backfills.run --only 2026-05-01_seed_widget_owner
"""

from __future__ import annotations

import argparse
import logging
import sys

from scripts.backfills._runner import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run pending data backfills.")
    parser.add_argument("--dry-run", action="store_true", help="Log what would change without writing.")
    parser.add_argument(
        "--only",
        help="Run a single backfill by NAME, ignoring applied state. Useful to retry one.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ran = run(dry_run=args.dry_run, only=args.only)
    print(f"Backfills applied: {ran}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
