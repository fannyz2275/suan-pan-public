"""Spec B harness — shared fixtures, hypothesis profiles, CI guards.

See docs/superpowers/specs/2026-05-09-eval-backend-spec.md.
"""
from __future__ import annotations

import os

import pytest
from hypothesis import Verbosity, settings
from syrupy.extensions.json import JSONSnapshotExtension


# ---------------------------------------------------------------------------
# Hypothesis profiles — fast for CI, thorough for nightly (§6.0).
# ---------------------------------------------------------------------------

settings.register_profile(
    "fast",
    max_examples=50,
    deadline=2000,
    verbosity=Verbosity.normal,
)
settings.register_profile(
    "thorough",
    max_examples=500,
    deadline=10000,
    verbosity=Verbosity.verbose,
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "fast"))


# ---------------------------------------------------------------------------
# CI guard — refuse to commit fresh snapshots from a CI run (§5.3).
# ---------------------------------------------------------------------------

def pytest_collection_finish(session: pytest.Session) -> None:
    if os.getenv("CI") and "--snapshot-update" in session.config.invocation_params.args:
        pytest.fail(
            "--snapshot-update is forbidden in CI. "
            "Generate snapshots locally and commit."
        )


# ---------------------------------------------------------------------------
# JSON-format syrupy fixture (§5.2).
# ---------------------------------------------------------------------------

@pytest.fixture
def snapshot_json(snapshot):
    return snapshot.use_extension(JSONSnapshotExtension)
