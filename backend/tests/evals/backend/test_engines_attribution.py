"""Spec B Phase 2 — engine module test for app.portfolio.attribution.

The I1 identity invariant lives in test_invariants_portfolio.py; this file
locks in the per-bucket dollar values via golden snapshots.
"""
from __future__ import annotations

from app.portfolio.attribution import compute_attribution


def test_attribution_mixed_txns_golden(snapshot_json):
    txns = [
        {"type": "transfer_in", "amount": 5_000.0},
        {"type": "transfer_out", "amount": -1_000.0},
        {"type": "dividend", "amount": 120.0},
        {"type": "interest", "amount": 30.0},
        {"type": "buy", "amount": -2_000.0},
        {"type": "sell", "amount": 2_500.0, "cost_basis_at_sell": 2_100.0},
        {"type": "fee", "amount": -25.0},
        {"type": "reinvest", "amount": 50.0},
    ]
    decomp = compute_attribution(
        start_value=100_000.0, end_value=110_000.0, transactions=txns,
    )
    assert decomp == snapshot_json


def test_attribution_unattributed_residual_golden(snapshot_json):
    """When clean_market_estimate is supplied, market is pinned and residual flows
    to unattributed."""
    decomp = compute_attribution(
        start_value=10_000.0,
        end_value=11_500.0,
        transactions=[{"type": "dividend", "amount": 50.0}],
        clean_market_estimate=1_000.0,
    )
    assert decomp == snapshot_json


def test_attribution_no_basis_falls_back_to_cash_impact():
    """When any sell is missing cost_basis_at_sell, trades = net cash impact."""
    decomp = compute_attribution(
        start_value=10_000.0,
        end_value=10_500.0,
        transactions=[
            {"type": "sell", "amount": 1_000.0},  # no cost_basis_at_sell
            {"type": "buy", "amount": -800.0},
        ],
    )
    assert decomp["trades_has_basis"] is False
    assert decomp["trades"] == 200.0


def test_attribution_buy_only_uses_cash_impact_fallback():
    """With buys but no sells, the realized-P&L path can't run; the fallback
    uses raw cash impact and reports trades_has_basis=False."""
    decomp = compute_attribution(
        start_value=10_000.0,
        end_value=10_500.0,
        transactions=[{"type": "buy", "amount": -500.0}],
    )
    assert decomp["trades_has_basis"] is False
    assert decomp["trades"] == -500.0


def test_attribution_empty_transactions():
    decomp = compute_attribution(
        start_value=10_000.0, end_value=11_000.0, transactions=[],
    )
    assert decomp["contributions"] == 0
    assert decomp["dividends"] == 0
    assert decomp["trades"] == 0
    # market absorbs the full delta when no clean_market_estimate
    assert decomp["market"] == 1_000.0
    assert decomp["unattributed"] == 0
