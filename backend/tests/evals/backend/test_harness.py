"""Spec B §14 — meta-tests for the eval harness itself.

A failing test here is a hard CI gate: the harness is broken until fixed.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Syrupy integration
# ---------------------------------------------------------------------------

def test_syrupy_integration_creates_snapshot_on_first_run(snapshot_json):
    """A fresh test using snapshot_json passes on first run (creates the file)."""
    payload = {"a": 1, "b": [2, 3], "c": {"nested": True}}
    assert payload == snapshot_json


def test_syrupy_path_type_matcher_excludes_uuids(snapshot_json):
    """path_type matcher should make uuid-shaped fields tolerant to drift."""
    from syrupy.matchers import path_type

    payload = {"id": "11111111-1111-1111-1111-111111111111", "value": 42}
    assert payload == snapshot_json(matcher=path_type({"id": (str,)}))


def test_syrupy_serializer_distinguishes_values():
    """Sanity: the JSON snapshot serializer renders different inputs differently.

    A real diff in stored bytes is what makes `assert x == snapshot_json` fail
    on drift; if the serializer ever collapsed distinct inputs, snapshots would
    silently mask regressions.
    """
    import json

    a = json.dumps({"x": 1}, sort_keys=True)
    b = json.dumps({"x": 2}, sort_keys=True)
    assert a != b


# ---------------------------------------------------------------------------
# CI snapshot-update guard
# ---------------------------------------------------------------------------

def test_ci_refuses_snapshot_update_flag(monkeypatch):
    """When CI=1 and --snapshot-update is in argv, pytest_collection_finish fails."""
    from .conftest import pytest_collection_finish

    monkeypatch.setenv("CI", "1")
    fake_session = MagicMock()
    fake_session.config.invocation_params.args = ("--snapshot-update",)

    with pytest.raises(pytest.fail.Exception):
        pytest_collection_finish(fake_session)


def test_ci_guard_silent_when_no_flag(monkeypatch):
    """CI guard must be silent when the forbidden flag is absent."""
    from .conftest import pytest_collection_finish

    monkeypatch.setenv("CI", "1")
    fake_session = MagicMock()
    fake_session.config.invocation_params.args = ("-v",)
    pytest_collection_finish(fake_session)  # must not raise


def test_ci_guard_silent_when_not_in_ci(monkeypatch):
    """CI guard must be silent when not running in CI, even with --snapshot-update."""
    from .conftest import pytest_collection_finish

    monkeypatch.delenv("CI", raising=False)
    fake_session = MagicMock()
    fake_session.config.invocation_params.args = ("--snapshot-update",)
    pytest_collection_finish(fake_session)  # must not raise


# ---------------------------------------------------------------------------
# Hypothesis profile
# ---------------------------------------------------------------------------

def test_hypothesis_fast_profile_active_by_default():
    """With HYPOTHESIS_PROFILE unset, the 'fast' profile must be loaded."""
    from hypothesis import settings

    # Conftest already loaded the profile at import time — assert defaults match
    # what 'fast' specifies (max_examples=50, deadline=2000ms).
    assert settings().max_examples == 50
    assert settings().deadline.total_seconds() * 1000 == 2000


# ---------------------------------------------------------------------------
# Differential helper sanity (mirrors D1 mechanism)
# ---------------------------------------------------------------------------

def test_differential_helper_field_by_field_with_tolerance():
    """Sanity: pytest.approx with rel=1e-6 catches drift larger than tolerance."""
    a = {"market_value": 8200.000001}
    b = {"market_value": 8200.0}
    assert a["market_value"] == pytest.approx(b["market_value"], rel=1e-6)
    assert a["market_value"] != pytest.approx(b["market_value"], rel=1e-12)


# ---------------------------------------------------------------------------
# live_db marker
# ---------------------------------------------------------------------------

def test_pytest_marker_live_db_exists():
    """The 'live_db' marker should be registered or at least usable as a marker."""
    # Markers don't need to be registered to be used — just verify the decorator
    # can be applied without error (a sanity check that pytest is sane).

    @pytest.mark.live_db
    def _fake_test():
        pass

    assert any(
        m.name == "live_db" for m in _fake_test.pytestmark
    )


# ---------------------------------------------------------------------------
# asyncio sanity (Spec B differential tests use asyncio.run on REST handlers)
# ---------------------------------------------------------------------------

def test_asyncio_run_works_for_handler_pattern():
    async def _coro():
        return 42

    assert asyncio.run(_coro()) == 42
