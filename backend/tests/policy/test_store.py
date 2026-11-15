"""Unit tests for app.policy.store. DB is mocked; this is thin Supabase
glue, but the lookup-vs-reinforce upsert path has real branching worth
covering."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.policy import store
from app.policy.schema import Domain


def _row(**overrides) -> dict:
    base = {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "domain": "categorize",
        "key": "description:starbucks",
        "value": {"category": "Food"},
        "source_note_id": None,
        "strength": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_reinforced_at": datetime.now(timezone.utc).isoformat(),
        "retired_at": None,
    }
    base.update(overrides)
    return base


# ---- lookup ----------------------------------------------------------------


def test_lookup_returns_override_when_row_exists():
    db = MagicMock()
    chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value.eq.return_value
        .is_.return_value.limit.return_value
    )
    chain.execute.return_value = SimpleNamespace(data=[_row()])

    out = store.lookup(
        db, user_id=uuid4(), domain=Domain.CATEGORIZE, key="description:starbucks",
    )

    assert out is not None
    assert out.value == {"category": "Food"}


def test_lookup_returns_none_when_no_row():
    db = MagicMock()
    chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value.eq.return_value
        .is_.return_value.limit.return_value
    )
    chain.execute.return_value = SimpleNamespace(data=[])

    out = store.lookup(
        db, user_id=uuid4(), domain=Domain.CATEGORIZE, key="description:starbucks",
    )

    assert out is None


def test_lookup_swallows_db_error_and_returns_none():
    """Engine reads must NEVER throw — a bad policy table read should
    fall back to unbiased engine behavior, not 500 the user's request."""
    db = MagicMock()
    db.table.side_effect = RuntimeError("DB down")

    out = store.lookup(
        db, user_id=uuid4(), domain=Domain.CATEGORIZE, key="description:x",
    )

    assert out is None


def test_lookup_accepts_string_domain():
    """Some callers may pass the raw string for convenience; the lookup
    should accept both the enum and the string form."""
    db = MagicMock()
    chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value.eq.return_value
        .is_.return_value.limit.return_value
    )
    chain.execute.return_value = SimpleNamespace(data=[_row()])

    out = store.lookup(
        db, user_id=uuid4(), domain="categorize", key="description:starbucks",
    )
    assert out is not None


# ---- insert_or_reinforce ---------------------------------------------------


def test_insert_path_when_no_existing_row():
    db = MagicMock()
    select_chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value.eq.return_value.limit.return_value
    )
    select_chain.execute.return_value = SimpleNamespace(data=[])

    insert_chain = db.table.return_value.insert.return_value
    insert_chain.execute.return_value = SimpleNamespace(data=[_row(strength=1)])

    out = store.insert_or_reinforce(
        db, user_id=uuid4(), domain=Domain.CATEGORIZE,
        key="description:starbucks", value={"category": "Food"},
    )
    assert out.strength == 1


def test_reinforce_path_bumps_strength_when_existing():
    db = MagicMock()
    select_chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value.eq.return_value.limit.return_value
    )
    select_chain.execute.return_value = SimpleNamespace(data=[_row(strength=3)])

    update_chain = (
        db.table.return_value.update.return_value.eq.return_value
    )
    update_chain.execute.return_value = SimpleNamespace(data=[_row(strength=4)])

    out = store.insert_or_reinforce(
        db, user_id=uuid4(), domain=Domain.CATEGORIZE,
        key="description:starbucks", value={"category": "Food"},
    )
    assert out.strength == 4

    # Verify the update payload bumped strength to 4 + cleared retired_at
    update_call = db.table.return_value.update.call_args.args[0]
    assert update_call["strength"] == 4
    assert update_call["retired_at"] is None
    assert update_call["value"] == {"category": "Food"}


def test_insert_payload_includes_source_note_id_when_given():
    db = MagicMock()
    select_chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value.eq.return_value.limit.return_value
    )
    select_chain.execute.return_value = SimpleNamespace(data=[])
    db.table.return_value.insert.return_value.execute.return_value = SimpleNamespace(
        data=[_row()]
    )

    note_id = uuid4()
    store.insert_or_reinforce(
        db, user_id=uuid4(), domain=Domain.CATEGORIZE,
        key="description:starbucks", value={"category": "Food"},
        source_note_id=note_id,
    )

    payload = db.table.return_value.insert.call_args.args[0]
    assert payload["source_note_id"] == str(note_id)


# ---- list_for_user ---------------------------------------------------------


def test_list_for_user_filters_retired_by_default():
    db = MagicMock()
    chain_no_retired = (
        db.table.return_value.select.return_value
        .eq.return_value.is_.return_value.order.return_value
    )
    chain_no_retired.execute.return_value = SimpleNamespace(data=[_row()])

    rows = store.list_for_user(db, user_id=uuid4())
    assert len(rows) == 1


def test_list_for_user_include_retired_skips_filter():
    db = MagicMock()
    chain_with_retired = (
        db.table.return_value.select.return_value.eq.return_value.order.return_value
    )
    chain_with_retired.execute.return_value = SimpleNamespace(
        data=[_row(), _row(retired_at=datetime.now(timezone.utc).isoformat())]
    )

    rows = store.list_for_user(db, user_id=uuid4(), include_retired=True)
    assert len(rows) == 2


def test_list_for_user_can_filter_by_domain():
    db = MagicMock()
    # When domain is given, the chain has an extra .eq before .is_
    chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value.is_.return_value.order.return_value
    )
    chain.execute.return_value = SimpleNamespace(data=[_row()])

    rows = store.list_for_user(db, user_id=uuid4(), domain=Domain.CATEGORIZE)
    assert len(rows) == 1
