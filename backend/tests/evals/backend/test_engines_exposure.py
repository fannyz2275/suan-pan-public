"""Spec B Phase 2 — engine module test for app.portfolio.exposure.

I2 (percent sums to 100%) and I3 (look-through residual non-negative) are
embedded here since they exercise compute_exposure directly.
"""
from __future__ import annotations

import pytest

from app.portfolio.exposure import compute_exposure


# Reference table reused across tests.
def _refs() -> dict:
    return {
        "NVDA": {"asset_class": "equity", "sector": "Technology", "region": "US"},
        "AAPL": {"asset_class": "equity", "sector": "Technology", "region": "US"},
        "MSFT": {"asset_class": "equity", "sector": "Technology", "region": "US"},
        "BND": {"asset_class": "fixed_income", "sector": None, "region": "US"},
        "VOO": {
            "asset_class": "equity", "sector": None, "region": "US",
            "look_through": [
                {"ticker": "AAPL", "weight": 0.07},
                {"ticker": "MSFT", "weight": 0.06},
            ],
        },
    }


def test_exposure_etf_with_look_through_sector_golden(snapshot_json):
    holdings = [
        {"ticker": "VOO", "market_value": 10_000.0},
        {"ticker": "BND", "market_value": 5_000.0},
    ]
    slices = compute_exposure(holdings, _refs(), dimension="sector")
    assert slices == snapshot_json


def test_exposure_asset_class_no_look_through(snapshot_json):
    """asset_class never uses look-through, even on ETFs."""
    holdings = [
        {"ticker": "VOO", "market_value": 10_000.0},
        {"ticker": "BND", "market_value": 5_000.0},
    ]
    slices = compute_exposure(holdings, _refs(), dimension="asset_class")
    assert slices == snapshot_json


# ---------------------------------------------------------------------------
# I2 — percent sums to 100%
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dimension", ["asset_class", "sector", "region"])
def test_invariant_i2_percentages_sum_to_100(dimension):
    holdings = [
        {"ticker": "NVDA", "market_value": 8_200.0},
        {"ticker": "AAPL", "market_value": 1_000.0},
        {"ticker": "BND", "market_value": 500.0},
        {"ticker": "VOO", "market_value": 4_000.0},
    ]
    slices = compute_exposure(holdings, _refs(), dimension=dimension)
    total_pct = sum(s["percent"] for s in slices)
    assert abs(total_pct - 100.0) <= 0.5


def test_invariant_i2_single_holding_yields_100_percent():
    """Edge case from §8: a single holding yields exactly 100% in its slice."""
    holdings = [{"ticker": "NVDA", "market_value": 1_000.0}]
    slices = compute_exposure(holdings, _refs(), dimension="asset_class")
    assert len(slices) == 1
    assert slices[0]["percent"] == pytest.approx(100.0, abs=1e-6)


def test_exposure_empty_holdings_returns_empty_list():
    assert compute_exposure([], _refs(), dimension="asset_class") == []


# ---------------------------------------------------------------------------
# I3 — look-through residual non-negative
# ---------------------------------------------------------------------------

def test_invariant_i3_look_through_weights_sum_le_1():
    refs = _refs()
    for ticker, ref in refs.items():
        if ref.get("look_through"):
            total_weight = sum(item["weight"] for item in ref["look_through"])
            assert total_weight <= 1.0 + 1e-9, (
                f"{ticker} look_through weights sum to {total_weight}"
            )


def test_invariant_i3_residual_is_non_negative_in_output():
    """When a single ETF is the only holding, its residual share must show up in
    its own label (no negative or missing share)."""
    holdings = [{"ticker": "VOO", "market_value": 1_000.0}]
    slices = compute_exposure(holdings, _refs(), dimension="sector")
    # The "Other" bucket holds VOO's residual (1 - 0.07 - 0.06 = 0.87 → $870)
    other = next(s for s in slices if s["label"] == "Other")
    assert other["market_value"] == pytest.approx(870.0, abs=1e-2)
    assert other["market_value"] >= 0
