"""Runner-level tests: discovery validates module shape; applied state skips
already-applied scripts; --only ignores applied state."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from scripts.backfills import _runner


def _make_module(modname: str, *, name: str | None = "2026-05-01_demo", apply=lambda db, *, dry_run: None):
    mod = types.ModuleType(f"scripts.backfills.{modname}")
    if name is not None:
        mod.NAME = name
    if apply is not None:
        mod.apply = apply
    sys.modules[mod.__name__] = mod
    return mod


def _patch_discover_with(modules: list[tuple[str, types.ModuleType]]):
    """Stub pkgutil.iter_modules + importlib.import_module to return the given
    fake modules, so we don't need to write real files for each test."""

    def fake_iter(_path):
        return [(None, modname, False) for modname, _ in modules]

    by_name = {f"scripts.backfills.{modname}": mod for modname, mod in modules}

    def fake_import(name):
        return by_name[name]

    return patch.object(_runner.pkgutil, "iter_modules", fake_iter), patch.object(
        _runner.importlib, "import_module", side_effect=fake_import
    )


def test_discover_sorts_by_name():
    a = _make_module("zzz_a", name="2026-05-01_a")
    b = _make_module("aaa_b", name="2026-04-01_b")
    iter_p, imp_p = _patch_discover_with([("zzz_a", a), ("aaa_b", b)])
    with iter_p, imp_p:
        out = _runner.discover()
    assert [b_.name for b_ in out] == ["2026-04-01_b", "2026-05-01_a"]


def test_discover_skips_framework_modules():
    """`run` (the CLI entry point) and other framework helpers must not be
    treated as backfills — they have no NAME/apply exports by design.

    Regression for the bug that surfaced when the first real backfill was
    added: discover() iterated all non-underscore modules and crashed on
    the CLI module itself.
    """
    real = _make_module("real_one", name="2026-05-01_a")
    cli = _make_module("run")  # no NAME, no apply — must be skipped, not raise
    iter_p, imp_p = _patch_discover_with([("run", cli), ("real_one", real)])
    with iter_p, imp_p:
        out = _runner.discover()
    assert [b.name for b in out] == ["2026-05-01_a"]


def test_discover_rejects_bad_name():
    bad = _make_module("bad", name="not-a-date")
    iter_p, imp_p = _patch_discover_with([("bad", bad)])
    with iter_p, imp_p, pytest.raises(RuntimeError, match="must match"):
        _runner.discover()


def test_discover_rejects_missing_apply():
    mod = _make_module("missing", name="2026-05-01_m", apply=None)
    iter_p, imp_p = _patch_discover_with([("missing", mod)])
    with iter_p, imp_p, pytest.raises(RuntimeError, match="must export"):
        _runner.discover()


def test_run_skips_already_applied():
    calls: list[str] = []

    def apply_a(db, *, dry_run): calls.append("a")
    def apply_b(db, *, dry_run): calls.append("b")

    mod_a = _make_module("a", name="2026-05-01_a", apply=apply_a)
    mod_b = _make_module("b", name="2026-05-02_b", apply=apply_b)

    fake_db = MagicMock()
    # _applied_set returns {"2026-05-01_a"}; only b should run.
    fake_db.table.return_value.select.return_value.execute.return_value.data = [
        {"name": "2026-05-01_a"}
    ]

    iter_p, imp_p = _patch_discover_with([("a", mod_a), ("b", mod_b)])
    with iter_p, imp_p, patch.object(_runner, "get_admin_db", return_value=fake_db):
        ran = _runner.run(dry_run=False, only=None)

    assert calls == ["b"]
    assert ran == 1


def test_run_only_ignores_applied_state():
    """--only is the retry path: caller knows what they want, we don't second-
    guess by checking applied_backfills."""
    calls: list[str] = []

    def apply_a(db, *, dry_run): calls.append("a")

    mod_a = _make_module("a", name="2026-05-01_a", apply=apply_a)

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.execute.return_value.data = [
        {"name": "2026-05-01_a"}
    ]

    iter_p, imp_p = _patch_discover_with([("a", mod_a)])
    with iter_p, imp_p, patch.object(_runner, "get_admin_db", return_value=fake_db):
        ran = _runner.run(dry_run=False, only="2026-05-01_a")

    assert calls == ["a"]
    assert ran == 1


def test_run_dry_run_does_not_record_applied():
    calls: list[str] = []
    inserted: list[dict] = []

    def apply_a(db, *, dry_run): calls.append("a")

    mod_a = _make_module("a", name="2026-05-01_a", apply=apply_a)

    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.execute.return_value.data = []
    fake_db.table.return_value.upsert.side_effect = lambda payload: (
        inserted.append(payload) or fake_db.table.return_value
    )

    iter_p, imp_p = _patch_discover_with([("a", mod_a)])
    with iter_p, imp_p, patch.object(_runner, "get_admin_db", return_value=fake_db):
        _runner.run(dry_run=True, only=None)

    assert calls == ["a"]
    assert inserted == []  # no applied record on dry-run


def teardown_module(module):
    # Clean up any fake modules we registered.
    for k in list(sys.modules):
        if k.startswith("scripts.backfills.") and k != "scripts.backfills._runner":
            sys.modules.pop(k, None)
    # Make sure real package import still works.
    importlib.invalidate_caches()
