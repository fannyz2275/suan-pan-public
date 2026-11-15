"""Tests for balance_history.cache_patch + record_history.

cache_patch is the pure-Python denormalized-cache helper; record_history
inserts into account_balance_history. We mock the supabase client because
the production tests don't reach a live DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.finance.balance_history import cache_patch, record_history


# ---- cache_patch -----------------------------------------------------------


def test_cache_patch_insert_path_only_stamps_updated_at():
    """First write of an account: no `previous_balance`, just the timestamp."""
    out = cache_patch(None, 100.0)
    assert "balance_updated_at" in out
    assert "previous_balance" not in out
    assert "previous_balance_at" not in out


def test_cache_patch_no_op_write_only_refreshes_timestamp():
    """Same numeric balance → don't blow away history; just refresh."""
    existing = {"balance": 100, "balance_updated_at": "2026-01-01T00:00:00Z"}
    out = cache_patch(existing, 100.0)
    assert out == {"balance_updated_at": out["balance_updated_at"]}
    assert "previous_balance" not in out


def test_cache_patch_real_change_rotates_previous():
    existing = {
        "balance": 100,
        "balance_updated_at": "2026-01-01T00:00:00Z",
        "created_at": "2025-12-01T00:00:00Z",
    }
    out = cache_patch(existing, 200.0)
    assert out["previous_balance"] == 100
    assert out["previous_balance_at"] == "2026-01-01T00:00:00Z"
    assert out["balance_updated_at"] != "2026-01-01T00:00:00Z"


def test_cache_patch_falls_back_to_created_at_when_updated_at_missing():
    existing = {"balance": 100, "created_at": "2025-12-01T00:00:00Z"}
    out = cache_patch(existing, 200.0)
    assert out["previous_balance_at"] == "2025-12-01T00:00:00Z"


def test_cache_patch_none_balance_returns_empty():
    """A None balance is the schema's "don't touch" signal — emit no patch."""
    assert cache_patch(None, None) == {}
    assert cache_patch({"balance": 50}, None) == {}


# ---- record_history --------------------------------------------------------


def _mock_db_with_insert():
    """Returns (db, captured_payload). Calling db.table(...).insert(payload).execute()
    stores the payload for assertion."""
    captured: dict = {}

    table = MagicMock()
    insert = MagicMock()

    def _capture(payload):
        captured.update(payload)
        return execute_chain

    execute_chain = MagicMock()
    execute_chain.execute = MagicMock(return_value=MagicMock(data=[{}]))
    insert.side_effect = _capture
    table.insert = insert
    db = MagicMock()
    db.table = MagicMock(return_value=table)
    return db, captured, table


def test_record_history_inserts_one_row():
    db, captured, table = _mock_db_with_insert()
    record_history(
        db,
        account_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        balance=1234.56,
        source="manual",
    )
    table.insert.assert_called_once()
    assert captured["account_id"] == "00000000-0000-0000-0000-000000000001"
    assert captured["user_id"] == "00000000-0000-0000-0000-000000000002"
    assert captured["balance"] == 1234.56
    assert captured["source"] == "manual"
    # as_of defaulted; ensure ISO format with timezone.
    assert "T" in captured["as_of"]
    assert captured["as_of"].endswith("+00:00") or captured["as_of"].endswith("Z")


def test_record_history_uses_explicit_as_of():
    db, captured, _ = _mock_db_with_insert()
    when = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
    record_history(
        db, account_id="a", user_id="u", balance=10.0,
        source="plaid", as_of=when,
    )
    assert captured["as_of"] == when.isoformat()


def test_record_history_skips_on_none_balance():
    db, captured, table = _mock_db_with_insert()
    record_history(db, account_id="a", user_id="u", balance=None, source="manual")
    table.insert.assert_not_called()
    assert captured == {}


def test_record_history_swallows_db_errors():
    """A history-insert failure must not break the account write that called it."""
    db = MagicMock()
    db.table.return_value.insert.return_value.execute.side_effect = RuntimeError("db down")
    # Must not raise.
    record_history(db, account_id="a", user_id="u", balance=50.0, source="manual")


def test_record_history_source_values():
    """Sanity: the four sources used by the four write paths are accepted."""
    db, _, _ = _mock_db_with_insert()
    for src in ("initial", "manual", "plaid", "file_import"):
        record_history(db, account_id="a", user_id="u", balance=1.0, source=src)
