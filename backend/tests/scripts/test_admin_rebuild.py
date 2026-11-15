"""Smoke tests for the rebuild CLI: scoping, dry-run, error counting."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.admin import rebuild as rebuild_mod


def _fake_db_with_users(user_ids: list[str]) -> MagicMock:
    db = MagicMock()
    db.table.return_value.select.return_value.execute.return_value.data = [
        {"id": uid} for uid in user_ids
    ]
    return db


def test_rebuild_runs_each_step_per_user():
    db = _fake_db_with_users(["u1", "u2"])
    seen: list[tuple[str, str]] = []

    def fake_step(_db, uid):
        seen.append(("rescan", uid))

    fake = [rebuild_mod.RebuildStep(name="rescan", run=fake_step)]
    with patch.object(rebuild_mod, "get_admin_db", return_value=db), patch.object(
        rebuild_mod, "STEPS", fake
    ):
        summary = rebuild_mod.rebuild(user_id=None, dry_run=False)

    assert seen == [("rescan", "u1"), ("rescan", "u2")]
    assert summary == {"users": 2, "steps": 1, "errors": 0}


def test_rebuild_user_scope_limits_to_one():
    db = _fake_db_with_users(["u1", "u2"])
    seen: list[str] = []

    fake = [rebuild_mod.RebuildStep(name="rescan", run=lambda _db, uid: seen.append(uid))]
    with patch.object(rebuild_mod, "get_admin_db", return_value=db), patch.object(
        rebuild_mod, "STEPS", fake
    ):
        rebuild_mod.rebuild(user_id="u1", dry_run=False)

    assert seen == ["u1"]


def test_rebuild_dry_run_skips_step_calls():
    db = _fake_db_with_users(["u1"])
    seen: list[str] = []

    fake = [rebuild_mod.RebuildStep(name="rescan", run=lambda _db, uid: seen.append(uid))]
    with patch.object(rebuild_mod, "get_admin_db", return_value=db), patch.object(
        rebuild_mod, "STEPS", fake
    ):
        rebuild_mod.rebuild(user_id=None, dry_run=True)

    assert seen == []


def test_rebuild_one_failing_step_does_not_abort_others():
    db = _fake_db_with_users(["u1", "u2"])
    seen: list[str] = []

    def boom(_db, uid):
        if uid == "u1":
            raise RuntimeError("kaboom")
        seen.append(uid)

    fake = [rebuild_mod.RebuildStep(name="rescan", run=boom)]
    with patch.object(rebuild_mod, "get_admin_db", return_value=db), patch.object(
        rebuild_mod, "STEPS", fake
    ):
        summary = rebuild_mod.rebuild(user_id=None, dry_run=False)

    assert seen == ["u2"]
    assert summary["errors"] == 1


def test_main_returns_nonzero_when_errors():
    db = _fake_db_with_users(["u1"])
    fake = [rebuild_mod.RebuildStep(name="rescan", run=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))]
    with patch.object(rebuild_mod, "get_admin_db", return_value=db), patch.object(
        rebuild_mod, "STEPS", fake
    ):
        rc = rebuild_mod.main([])
    assert rc == 1
