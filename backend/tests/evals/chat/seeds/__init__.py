"""Seed factory dispatch table for chat dataset rows."""
from __future__ import annotations

from typing import Callable

from tests.evals.shared.seed import Seed
from tests.evals.chat.seeds.portfolio_attribution import single_account_2_holdings


def default_legacy_user() -> Seed:
    """Minimal seed for [LEGACY]-tagged transaction scenarios.

    A single checking account with no transactions or snapshots — enough
    for the advisor to call list_transactions without crashing. Realism is
    not the goal; the legacy scenarios are tagged [LEGACY] and don't gate
    releases.
    """
    return (
        Seed()
        .with_user(user_id="u-eval-c")
        .with_account(
            account_id="acc-eval-c-checking",
            name="Eval Checking",
            type="checking",
            balance=1000,
        )
    )


SEED_FACTORIES: dict[str, Callable[[], Seed]] = {
    "single_account_2_holdings": single_account_2_holdings,
    "default_legacy_user": default_legacy_user,
}


def get_seed(seed_id: str) -> Seed:
    """Look up a seed factory by name and return a fresh Seed."""
    if seed_id not in SEED_FACTORIES:
        raise KeyError(f"unknown seed_id: {seed_id!r}")
    return SEED_FACTORIES[seed_id]()
