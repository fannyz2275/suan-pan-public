"""
seed_runner — CLI module for seeding the eval DB before Playwright tests.

Usage (from repo root):
    python -m backend.tests.evals.shared.seed_runner --fixture single_brokerage

The globalSetup in frontend/e2e/global-setup.ts shells out to this command.
Exit code 0 on success, non-zero on any error so globalSetup can abort.
"""

from __future__ import annotations

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# Fixture definitions
# ---------------------------------------------------------------------------

def _build_single_brokerage():
    """Two snapshots, two holdings (AAPL + BND), one brokerage account."""
    from backend.tests.evals.shared.seed import Seed  # noqa: PLC0415

    return (
        Seed()
        .with_user(user_id="u-eval-a")
        .with_account(
            account_id="acc-brok-1",
            name="Fidelity Brokerage",
            type="brokerage",
            balance=50000,
        )
        .with_security(ticker="AAPL", asset_class="equity", sector="Technology", region="US")
        .with_security(ticker="BND", asset_class="fixed_income", sector=None, region="US")
        .with_snapshot(
            account_id="acc-brok-1",
            snapshot_date="2026-04-01",
            cash_value=5000.0,
            holdings=[
                {"ticker": "AAPL", "qty": 10, "price": 185.00, "cost_basis": 150.00},
                {"ticker": "BND",  "qty": 50, "price": 74.50,  "cost_basis": 74.00},
            ],
            total_value=12975.00,
        )
        .with_snapshot(
            account_id="acc-brok-1",
            snapshot_date="2026-05-01",
            cash_value=5100.0,
            holdings=[
                {"ticker": "AAPL", "qty": 10, "price": 190.00, "cost_basis": 150.00},
                {"ticker": "BND",  "qty": 50, "price": 73.80,  "cost_basis": 74.00},
            ],
            total_value=13090.00,
        )
    )


def _build_no_holdings():
    """Empty brokerage account — for empty-state tests."""
    from backend.tests.evals.shared.seed import Seed  # noqa: PLC0415

    return (
        Seed()
        .with_user(user_id="u-eval-empty")
        .with_account(
            account_id="acc-brok-2",
            name="Empty Brokerage",
            type="brokerage",
            balance=0,
        )
    )


FIXTURES: dict[str, callable] = {
    "single_brokerage": _build_single_brokerage,
    "no_holdings": _build_no_holdings,
}


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed the eval DB with a named fixture.",
    )
    parser.add_argument(
        "--fixture",
        required=True,
        choices=list(FIXTURES),
        help="Name of the fixture to apply.",
    )
    parser.add_argument(
        "--supabase-url",
        default=os.environ.get("SUPABASE_URL"),
        help="Supabase project URL (defaults to SUPABASE_URL env var).",
    )
    parser.add_argument(
        "--supabase-key",
        default=os.environ.get("SUPABASE_SERVICE_KEY"),
        help="Supabase service-role key (defaults to SUPABASE_SERVICE_KEY env var).",
    )
    args = parser.parse_args(argv)

    if not args.supabase_url or not args.supabase_key:
        print(
            "ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set "
            "(via env var or --supabase-url / --supabase-key).",
            file=sys.stderr,
        )
        return 1

    try:
        from supabase import create_client  # noqa: PLC0415
    except ImportError:
        print("ERROR: supabase-py not installed.", file=sys.stderr)
        return 1

    db = create_client(args.supabase_url, args.supabase_key)

    build_fn = FIXTURES[args.fixture]
    seed = build_fn()
    result = seed.apply(db)

    print(
        f"Fixture '{args.fixture}' applied: "
        f"user={result.user_id}, "
        f"accounts={list(result.account_ids.values())}, "
        f"snapshots={result.snapshot_ids}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
