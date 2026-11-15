"""Tests for app.profile.scales — single source of truth for the 1-5
identity scalars rendered into both the prompt and the UI tooltips."""
from __future__ import annotations

from app.profile.scales import (
    HORIZON_ANCHORS, RISK_ANCHORS, all_scales, render_horizon, render_risk,
)


def test_render_risk_in_range():
    assert render_risk(1) == "Risk 1/5 (capital preservation)"
    assert render_risk(3) == "Risk 3/5 (balanced)"
    assert render_risk(5) == "Risk 5/5 (high conviction)"


def test_render_horizon_in_range():
    assert render_horizon(1) == "Horizon 1/5 (<1 year)"
    assert render_horizon(5) == "Horizon 5/5 (>6 years)"


def test_render_returns_none_for_missing_or_out_of_range():
    """Missing / out-of-range silently drops — the one-liner skips the field."""
    assert render_risk(None) is None
    assert render_risk(0) is None
    assert render_risk(6) is None
    assert render_horizon(None) is None
    assert render_horizon(99) is None


def test_render_coerces_string_input():
    """DB rows can come back as strings from older code paths."""
    assert render_risk("3") == "Risk 3/5 (balanced)"


def test_all_scales_returns_both_axes_sorted():
    payload = all_scales()
    assert set(payload.keys()) == {"risk_tolerance", "time_horizon"}
    assert [a["value"] for a in payload["risk_tolerance"]] == [1, 2, 3, 4, 5]
    assert [a["value"] for a in payload["time_horizon"]] == [1, 2, 3, 4, 5]
    # Each anchor has the three required UX fields.
    for axis in payload.values():
        for a in axis:
            assert {"value", "label", "description"} <= set(a)


def test_anchor_dicts_cover_full_1_5_range():
    """Sanity: no gaps. Misses would silently drop tooltip notches in the UI."""
    assert sorted(RISK_ANCHORS) == [1, 2, 3, 4, 5]
    assert sorted(HORIZON_ANCHORS) == [1, 2, 3, 4, 5]


def test_anchor_shape_matches_frontend_contract():
    """Drift guard: the Anchor TypedDict's keys must match the frontend's
    ScaleAnchor interface (frontend/src/lib/profileScales.ts) field-for-field.

    If you rename / add / remove a key here, also update the TS interface and
    fix any consumers of `ScaleAnchor` in the React tree. The list below is
    the contract; failing this test means the two have drifted.
    """
    EXPECTED_KEYS = {"value", "label", "description"}
    for axis in (RISK_ANCHORS, HORIZON_ANCHORS):
        for value, anchor in axis.items():
            assert set(anchor.keys()) == EXPECTED_KEYS, (
                f"anchor {value} has unexpected keys: {set(anchor.keys())}"
            )
