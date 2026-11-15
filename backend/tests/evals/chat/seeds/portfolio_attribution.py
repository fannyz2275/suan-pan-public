"""Seed factory for portfolio attribution scenarios."""
from __future__ import annotations

from tests.evals.shared.seed import Seed


def single_account_2_holdings() -> Seed:
    """One brokerage account, two holdings (AAPL + BND), two snapshots a month apart.

    The attribution between snapshots is dominated by market change with
    near-zero unattributed bucket, so portfolio_get_attribution will produce
    a clean scenario for the rubric to score.
    """
    return (
        Seed()
        .with_user(user_id="u-eval-c")
        .with_account(
            account_id="acc-eval-c-brok",
            name="Eval Brokerage",
            type="brokerage",
            balance=50000,
        )
        .with_security(ticker="AAPL", asset_class="equity", sector="Technology", region="US")
        .with_security(ticker="BND", asset_class="fixed_income", sector=None, region="US")
        .with_snapshot(
            account_id="acc-eval-c-brok",
            snapshot_date="2026-04-01",
            cash_value=2000.0,
            holdings=[
                {"ticker": "AAPL", "qty": 100, "price": 180.00},
                {"ticker": "BND",  "qty": 200, "price": 75.00},
            ],
        )
        .with_snapshot(
            account_id="acc-eval-c-brok",
            snapshot_date="2026-05-01",
            cash_value=2000.0,
            holdings=[
                {"ticker": "AAPL", "qty": 100, "price": 192.00},  # +$1,200 market
                {"ticker": "BND",  "qty": 200, "price": 75.50},   # +$100 market
            ],
        )
    )
