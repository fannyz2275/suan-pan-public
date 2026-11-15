"""Spec B Phase 1 — engine module test for app.engine.snapshot.

Fixture id: `single-account-2-holdings` (informally — compute_snapshot operates on
account dicts directly, not portfolio_snapshots, so the seed shape is local).
"""
from __future__ import annotations

import pytest

from app.engine.snapshot import compute_snapshot


@pytest.fixture
def accounts_basic() -> list[dict]:
    """Mixed account types covering every branch of compute_snapshot."""
    return [
        {"type": "checking", "balance": 5_000.0},
        {"type": "savings", "balance": 12_500.0},
        {"type": "brokerage", "balance": 14_200.0},
        {"type": "retirement", "balance": 88_000.0},
        {
            "type": "property",
            "balance": 0.0,
            "estimated_value": 750_000.0,
        },
        {
            "type": "rsu",
            "vested_shares": 100,
            "unvested_shares": 200,
            "grant_price": 50.0,
        },
        {"type": "debt", "balance": -25_000.0},
    ]


def test_compute_snapshot_basic(accounts_basic, snapshot_json):
    """Golden snapshot of compute_snapshot for the canonical mixed-account fixture."""
    result = compute_snapshot(accounts_basic)
    assert result == snapshot_json


def test_compute_snapshot_empty():
    result = compute_snapshot([])
    assert result == {
        "liquid_assets": 0,
        "investment_assets": 0,
        "non_current_assets": 0,
        "total_liabilities": 0,
        "net_worth": 0,
        "liquid_net_worth": 0,
    }


def test_compute_snapshot_only_debt():
    result = compute_snapshot([{"type": "debt", "balance": -1_000.0}])
    assert result["total_liabilities"] == 1_000.0
    assert result["net_worth"] == -1_000.0
    assert result["liquid_net_worth"] == 0
