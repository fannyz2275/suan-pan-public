"""Unit tests for the note-importance backfill — focused on the resume
sentinel, the per-row scoring path, and the failed-IDs exclude that prevents
the runaway-refetch loop. DB and Gemini are mocked; no real Supabase needed."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from scripts.backfills import note_importance as bf


def _row(id_: str | None = None, content: str = "x", kind: str = "fact",
         importance_source: str | None = None) -> dict:
    prov = {} if importance_source is None else {"importance_source": importance_source}
    return {"id": id_ or str(uuid4()), "kind": kind, "content": content,
            "provenance": prov}


def _select_chain(db: MagicMock, returns: list[list[dict]]) -> list:
    """Wire the supabase select.eq.[not_.in_].limit.execute chain to return
    successive batches across calls. Returns the call list for inspection.
    Returns empty after exhausted."""
    table = db.table.return_value
    select = table.select.return_value
    eq = select.eq.return_value
    not_in_eq = eq.not_.in_.return_value  # used when exclude_ids is non-empty
    # When exclude_ids is empty, the chain skips .not_.in_ and goes straight to .limit.
    eq.limit.return_value.execute.side_effect = [
        SimpleNamespace(data=batch) for batch in (returns + [[]])
    ]
    not_in_eq.limit.return_value.execute.side_effect = [
        SimpleNamespace(data=batch) for batch in (returns + [[]])
    ]
    return [select, eq]


def test_module_exports_required_runner_contract():
    assert isinstance(bf.NAME, str)
    assert bf.NAME == "2026-05-02_note_importance"
    assert callable(bf.apply)
    # Runner expects sync apply with (db, *, dry_run) signature.
    import inspect
    sig = inspect.signature(bf.apply)
    assert "dry_run" in sig.parameters


def test_fetch_pending_filters_already_scored():
    """Rows whose provenance already records 'importance_source=llm' must be
    excluded — that's the resume sentinel that lets re-runs skip work."""
    rows = [
        _row(content="needs scoring"),
        _row(content="already scored", importance_source="llm"),
    ]
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=rows)

    pending = bf._fetch_pending(db, limit=10)

    assert len(pending) == 1
    assert pending[0]["content"] == "needs scoring"


def test_fetch_pending_with_exclude_ids_routes_through_not_in():
    """When the in-process failed-IDs set is non-empty, _fetch_pending must
    pass it through .not_.in_('id', ...) so the DB stops returning those rows.
    This is the guard against the runaway-refetch loop in B1."""
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.not_.in_.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])

    bf._fetch_pending(db, limit=10, exclude_ids={"bad-id-1", "bad-id-2"})

    # Verify .not_.in_ was called with the right column + the exclude list
    not_in_call = db.table.return_value.select.return_value.eq.return_value.not_.in_.call_args
    assert not_in_call.args[0] == "id"
    assert set(not_in_call.args[1]) == {"bad-id-1", "bad-id-2"}


@pytest.mark.asyncio
async def test_score_one_writes_importance_and_marks_provenance():
    db = MagicMock()
    db.table.return_value.update.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])
    gemini = MagicMock()
    row = _row(content="user is sole earner")

    with patch("scripts.backfills.note_importance.score_importance",
               new=AsyncMock(return_value=8)):
        out = await bf._score_one(db, gemini, row)

    assert out == 8
    payload = db.table.return_value.update.call_args.args[0]
    assert payload["importance"] == 8
    assert payload["provenance"]["importance_source"] == "llm"


@pytest.mark.asyncio
async def test_apply_async_dry_run_does_not_write():
    """dry_run logs what it would do, then returns — no .update calls."""
    rows = [_row(content="r1")]
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=rows)

    with patch.dict("os.environ", {"GOOGLE_API_KEY": "fake"}), \
         patch("google.genai.Client", return_value=MagicMock()):
        await bf._apply_async(db, dry_run=True)

    db.table.return_value.update.assert_not_called()


@pytest.mark.asyncio
async def test_apply_async_excludes_failed_ids_to_prevent_runaway_loop():
    """Regression for B1: when _score_one raises for every row in a batch,
    the failed IDs go into an in-process exclude set so the next _fetch_pending
    call doesn't redeliver them. Without this, the loop spins forever."""
    rows_first = [_row(id_=f"id-{i}", content=f"row{i}") for i in range(3)]

    fetch_calls: list[set[str]] = []

    def fake_fetch(db, limit, *, exclude_ids=None):
        # Snapshot what was passed in so we can assert on accumulation.
        fetch_calls.append(set(exclude_ids or []))
        if not fetch_calls or len(fetch_calls) == 1:
            return list(rows_first)
        return []  # second call: nothing left

    async def always_fails(db, gemini, row):
        raise RuntimeError("Gemini timeout")

    with patch.dict("os.environ", {"GOOGLE_API_KEY": "fake"}), \
         patch("google.genai.Client", return_value=MagicMock()), \
         patch("scripts.backfills.note_importance._fetch_pending",
               side_effect=fake_fetch), \
         patch("scripts.backfills.note_importance._score_one",
               side_effect=always_fails), \
         patch("scripts.backfills.note_importance.SLEEP_BETWEEN_BATCHES", 0):
        await bf._apply_async(MagicMock(), dry_run=False)

    # First fetch had no excludes; the second fetch must include all 3 failed IDs.
    assert fetch_calls[0] == set()
    assert fetch_calls[1] == {"id-0", "id-1", "id-2"}
