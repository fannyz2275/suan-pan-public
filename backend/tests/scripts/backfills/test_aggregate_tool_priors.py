"""Unit tests for the aggregate_tool_priors backfill — verifies the
runner contract + the per-bucket aggregation math + Wilson-scoring."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from scripts.backfills import aggregate_tool_priors as agg


def _log(*, user_id, tool_name, ctx, succeeded, created_at="2026-05-01T00:00:00Z"):
    return {
        "user_id": user_id, "tool_name": tool_name,
        "ctx_signature": ctx, "succeeded": succeeded,
        "created_at": created_at,
    }


def _mock_db_with_logs(batches: list[list[dict]]) -> MagicMock:
    """Wire .range().execute() to return successive batches and finally []."""
    db = MagicMock()
    chain = db.table.return_value.select.return_value.range.return_value
    chain.execute.side_effect = [
        SimpleNamespace(data=batch) for batch in (batches + [[]])
    ]
    return db


def test_module_exports_runner_contract():
    assert isinstance(agg.NAME, str)
    assert agg.NAME == "2026-05-03_aggregate_tool_priors"
    assert callable(agg.apply)
    import inspect
    sig = inspect.signature(agg.apply)
    assert "dry_run" in sig.parameters


def test_apply_dry_run_does_not_upsert():
    uid = str(uuid4())
    db = _mock_db_with_logs([[
        _log(user_id=uid, tool_name="get_snapshot", ctx="other", succeeded=True),
    ]])

    agg.apply(db, dry_run=True)

    db.table.return_value.upsert.assert_not_called()


def test_apply_aggregates_per_user_tool_ctx_bucket():
    uid_a = str(uuid4())
    uid_b = str(uuid4())
    logs = [
        _log(user_id=uid_a, tool_name="get_snapshot", ctx="other", succeeded=True),
        _log(user_id=uid_a, tool_name="get_snapshot", ctx="other", succeeded=True),
        _log(user_id=uid_a, tool_name="get_snapshot", ctx="other", succeeded=False),
        _log(user_id=uid_b, tool_name="get_snapshot", ctx="other", succeeded=True),
    ]
    db = _mock_db_with_logs([logs])

    agg.apply(db, dry_run=False)

    upserts = [c.args[0] for c in db.table.return_value.upsert.call_args_list]
    by_user = {p["user_id"]: p for p in upserts}

    # User A: 2 success / 1 miss
    assert by_user[uid_a]["success_count"] == 2
    assert by_user[uid_a]["miss_count"] == 1
    # User B: 1 success / 0 miss — but Wilson lower bound is < 1.0
    assert by_user[uid_b]["success_count"] == 1
    assert by_user[uid_b]["miss_count"] == 0
    assert 0.0 < by_user[uid_b]["utility_score"] < 1.0
    # User A's bigger sample size should produce a higher Wilson score
    # than user B's 1-for-1.
    assert by_user[uid_a]["utility_score"] > by_user[uid_b]["utility_score"]


def test_apply_uses_max_created_at_per_bucket():
    uid = str(uuid4())
    logs = [
        _log(user_id=uid, tool_name="x", ctx="other", succeeded=True,
             created_at="2026-04-01T00:00:00Z"),
        _log(user_id=uid, tool_name="x", ctx="other", succeeded=True,
             created_at="2026-05-01T12:00:00Z"),  # newest
        _log(user_id=uid, tool_name="x", ctx="other", succeeded=False,
             created_at="2026-04-15T00:00:00Z"),
    ]
    db = _mock_db_with_logs([logs])

    agg.apply(db, dry_run=False)

    upsert_payload = db.table.return_value.upsert.call_args.args[0]
    assert upsert_payload["last_used_at"] == "2026-05-01T12:00:00Z"


def test_apply_handles_empty_logs():
    """No rows in tool_call_logs → no upserts, no error."""
    db = _mock_db_with_logs([])
    agg.apply(db, dry_run=False)
    db.table.return_value.upsert.assert_not_called()


def test_apply_treats_missing_ctx_as_other():
    """Older log rows may have NULL ctx_signature; bucket them as 'other'
    rather than dropping or crashing."""
    uid = str(uuid4())
    logs = [
        {"user_id": uid, "tool_name": "x", "ctx_signature": None,
         "succeeded": True, "created_at": "2026-05-01T00:00:00Z"},
    ]
    db = _mock_db_with_logs([logs])

    agg.apply(db, dry_run=False)

    payload = db.table.return_value.upsert.call_args.args[0]
    assert payload["ctx_signature"] == "other"
