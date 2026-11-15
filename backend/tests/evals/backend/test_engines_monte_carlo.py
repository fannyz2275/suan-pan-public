"""Spec B Phase 2 — engine module test for app.engine.monte_carlo.

Includes invariant I7 — Monte Carlo determinism: identical percentile output
across N=5 same-seed runs.
"""
from __future__ import annotations

import pytest

from app.engine.monte_carlo import run_monte_carlo


def _params_30yr() -> dict:
    return {
        "initial_portfolio": 100_000.0,
        "monthly_contribution": 500.0,
        "years": 30,
        "simulations": 1_000,  # smaller than default 5000 for speed; still deterministic
    }


def test_monte_carlo_30yr_golden(snapshot_json):
    result = run_monte_carlo(**_params_30yr())
    assert result == snapshot_json


def test_monte_carlo_with_target_amount_includes_success_rate():
    result = run_monte_carlo(target_amount=500_000, **_params_30yr())
    assert "success_rate" in result
    assert 0.0 <= result["success_rate"] <= 1.0


def test_monte_carlo_percentiles_are_ordered():
    result = run_monte_carlo(**_params_30yr())
    assert result["p10"] <= result["p25"] <= result["p50"] <= result["p75"] <= result["p90"]


# ---------------------------------------------------------------------------
# I7 — Determinism invariant
# ---------------------------------------------------------------------------

def test_invariant_i7_monte_carlo_determinism():
    """Same seed → identical percentile outputs across 5 runs."""
    runs = [run_monte_carlo(**_params_30yr()) for _ in range(5)]
    first = runs[0]
    for r in runs[1:]:
        assert r["p10"] == first["p10"]
        assert r["p25"] == first["p25"]
        assert r["p50"] == first["p50"]
        assert r["p75"] == first["p75"]
        assert r["p90"] == first["p90"]


@pytest.mark.parametrize("simulations", [100, 250, 1_000])
def test_monte_carlo_determinism_at_various_simulation_counts(simulations):
    """Determinism must hold regardless of `simulations`."""
    a = run_monte_carlo(
        initial_portfolio=50_000, monthly_contribution=200,
        years=10, simulations=simulations,
    )
    b = run_monte_carlo(
        initial_portfolio=50_000, monthly_contribution=200,
        years=10, simulations=simulations,
    )
    assert a == b
