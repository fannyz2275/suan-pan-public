"""Spec B Phase 2 — engine module test for app.engine.simulation.

simulate_decision delegates to score_goal_feasibility, which reads date.today();
freeze it to a known date for stable goldens. Verifies §4a invariants:
"All goal scores change by ≤ 100 pp; scores remain ∈ [0,100]".
"""
from __future__ import annotations

from datetime import date

import pytest

from app.engine import feasibility as feas_mod
from app.engine.simulation import simulate_decision


_TODAY = date(2026, 5, 9)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _TODAY


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(feas_mod, "date", _FrozenDate)


@pytest.fixture
def sim_inputs():
    accounts = [
        {"type": "checking", "balance": 8_000.0},
        {"type": "savings", "balance": 22_000.0},
        {"type": "brokerage", "balance": 60_000.0},
    ]
    goals = [
        {
            "name": "Emergency Fund",
            "target_amount": 30_000.0,
            "current_progress": 12_000.0,
            "target_date": "2027-05-01",
        },
        {
            "name": "Down Payment",
            "target_amount": 150_000.0,
            "current_progress": 30_000.0,
            "target_date": "2030-05-01",
        },
    ]
    return {
        "accounts": accounts,
        "goals": goals,
        "monthly_income": 12_000.0,
        "monthly_expenses": 7_500.0,
    }


def test_simulate_car_purchase_golden(sim_inputs, snapshot_json):
    decision = {
        "description": "Buy a $35k car (financed at $500/mo)",
        "upfront_cost": 35_000.0,
        "monthly_delta": -500.0,
        "asset_value": 35_000.0,
    }
    result = simulate_decision(decision=decision, **sim_inputs)
    assert result == snapshot_json


def test_simulate_invariants_score_bounds_and_delta(sim_inputs):
    decision = {
        "description": "test",
        "upfront_cost": 5_000.0,
        "monthly_delta": -250.0,
        "asset_value": 0.0,
    }
    result = simulate_decision(decision=decision, **sim_inputs)
    for impact in result["goal_impacts"]:
        assert 0 <= impact["score_before"] <= 100
        assert 0 <= impact["score_after"] <= 100
        assert abs(impact["score_delta"]) <= 100


def test_simulate_zero_decision_is_noop(sim_inputs):
    """upfront_cost=0 + monthly_delta=0 must leave every goal score unchanged."""
    result = simulate_decision(
        decision={"description": "noop"}, **sim_inputs
    )
    for impact in result["goal_impacts"]:
        assert impact["score_delta"] == 0


def test_simulate_liquid_override_pins_liquid_before(sim_inputs):
    result = simulate_decision(
        decision={"description": "test", "upfront_cost": 1_000.0},
        liquid_override=99_999.0,
        **sim_inputs,
    )
    assert result["liquid_assets_before"] == 99_999.0
    assert result["liquid_assets_after"] == 98_999.0
