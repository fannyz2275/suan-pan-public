import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from app.notes.compaction import prune_examples_for_pattern, merge_preferences_for_user
from app.notes.schema import NewNote, NoteKind, NoteSource
from app.notes.store import insert_note


@pytest.mark.asyncio
async def test_forecast_overrides_are_not_llm_merge_candidates():
    db, gemini = MagicMock(), MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value.data = [
        {'id':'settings', 'content':'Forecast overrides', 'tags':['engine:forecast-settings']},
        {'id':'preference', 'content':'Keep a reserve', 'tags':['topic:saving']},
    ]
    assert await merge_preferences_for_user(db=db, gemini=gemini, user_id=uuid4()) == 0
    gemini.aio.models.generate_content.assert_not_called()


@pytest.mark.integration
def test_prune_examples_caps_at_per_tag_limit(supabase_admin_db, test_user):
    uid, _ = test_user
    for i in range(12):
        insert_note(supabase_admin_db, NewNote(
            user_id=uid, kind=NoteKind.EXAMPLE,
            content=f"ex {i}",
            tags=["topic:advisor-confirmed", f"entity:profile:{uid}"],
            source=NoteSource.MESSAGE_FEEDBACK,
            provenance={"label": "good_advice", "message_id": f"m{i}"},
        ))
    pruned = prune_examples_for_pattern(
        supabase_admin_db, user_id=uid, primary_tag="topic:advisor-confirmed", cap=8,
    )
    assert pruned == 4
    live = (
        supabase_admin_db.table("user_notes").select("id")
        .eq("user_id", str(uid)).eq("kind", "example")
        .is_("expires_at", "null")
        .contains("tags", ["topic:advisor-confirmed"])
        .execute().data
    )
    assert len(live) == 8


@pytest.mark.asyncio
async def test_merge_preferences_collapses_near_duplicates(monkeypatch):
    uid = uuid4()
    fake_db = MagicMock()
    fake_db.table.return_value.select.return_value.eq.return_value.eq.return_value\
        .is_.return_value.execute.return_value.data = [
            {"id": "p1", "content": "Won't tap 401k early", "tags": ["topic:retirement"], "strength": 2},
            {"id": "p2", "content": "Never withdraw from 401k before retirement", "tags": ["topic:retirement"], "strength": 1},
            {"id": "p3", "content": "Dining out is non-negotiable", "tags": ["topic:dining"], "strength": 1},
        ]

    fake_resp = MagicMock()
    import json
    fake_resp.text = json.dumps({"preferences": [
        {"content": "Will not tap 401k early under any circumstances", "tags": ["retirement"], "strength": 3, "supersedes": ["p1", "p2"]},
        {"content": "Dining out is non-negotiable", "tags": ["dining"], "strength": 1, "supersedes": ["p3"]},
    ]})
    fake_gemini = MagicMock()
    fake_gemini.aio.models.generate_content = AsyncMock(return_value=fake_resp)

    monkeypatch.setattr("app.notes.compaction.embed_text",
                       AsyncMock(return_value=[0.0] * 768))

    inserted = []
    superseded_calls = []
    monkeypatch.setattr("app.notes.compaction.insert_note",
                       lambda db, new: inserted.append(new) or MagicMock(id=uuid4()))
    monkeypatch.setattr("app.notes.compaction.supersede_notes",
                       lambda db, **kw: superseded_calls.append(kw))

    n = await merge_preferences_for_user(db=fake_db, gemini=fake_gemini, user_id=uid)
    assert n == 2
    assert len(superseded_calls) == 2
