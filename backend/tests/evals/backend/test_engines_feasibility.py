"""Spec B Phase 2 — engine module test for app.engine.feasibility.

`score_goal_feasibility` reads `date.today()` for months_available, so we patch
the module-level `date` to a fixed reference date for deterministic snapshots.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.engine import feasibility as feas_mod
from app.engine.feasibility import score_goal_feasibility


_TODAY = date(2026, 5, 9)


class _FrozenDate(date):
    """date subclass with today() pinned to _TODAY."""

    @classmethod
    def today(cls) -> date:
        return _TODAY


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(feas_mod, "date", _FrozenDate)


def test_score_on_track(snapshot_json):
    result = score_goal_feasibility(
        target_amount=50_000.0,
        current_progress=10_000.0,
        monthly_surplus=4_000.0,
        target_date="2027-05-01",
    )
    assert result == snapshot_json
    assert 0 <= result["feasibility_score"] <= 100
    assert result["months_to_goal"] > 0


def test_score_at_risk(snapshot_json):
    result = score_goal_feasibility(
        target_amount=50_000.0,
        current_progress=10_000.0,
        monthly_surplus=2_500.0,
        target_date="2027-05-01",
    )
    assert result == snapshot_json


def test_score_off_track_zero_surplus():
    result = score_goal_feasibility(
        target_amount=50_000.0,
        current_progress=10_000.0,
        monthly_surplus=0.0,
        target_date="2027-05-01",
    )
    assert result["feasibility_score"] == 0.0
    assert result["status"] == "off_track"
    assert result["months_to_goal"] is None


def test_score_already_complete():
    result = score_goal_feasibility(
        target_amount=10_000.0,
        current_progress=12_000.0,
        monthly_surplus=500.0,
        target_date="2027-01-01",
    )
    assert result["feasibility_score"] == 100.0
    assert result["status"] == "on_track"
    assert result["months_to_goal"] == 0


def test_score_target_in_past():
    """When target_date is at/before today, months_available is 0."""
    result = score_goal_feasibility(
        target_amount=50_000.0,
        current_progress=10_000.0,
        monthly_surplus=4_000.0,
        target_date="2026-04-01",
    )
    assert result["months_available"] == 0
    assert result["status"] == "off_track"
