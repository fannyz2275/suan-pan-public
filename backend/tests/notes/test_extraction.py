import json
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from app.notes.extraction import extract_for_user, _build_prompt, _ingest_examples


def test_forecast_event_memory_validates_quote_and_reuses_stable_identity():
    from app.notes.extraction import _ingest_forecast_events
    db = MagicMock()
    uid = uuid4()
    items = [{'label':'Wedding', 'amount':6000, 'month':'2027-06',
              'source_quote':'My wedding will cost $6,000 in June 2027.'}]
    messages = [{'role':'user', 'content':items[0]['source_quote']}]
    assert _ingest_forecast_events(db, uid, items, messages) == 1
    first = db.table.return_value.upsert.call_args.args[0]
    assert first['provenance']['forecast_event']['amount'] == 6000
    assert _ingest_forecast_events(db, uid, items, messages) == 1
    assert db.table.return_value.upsert.call_args.args[0]['id'] == first['id']
    assert _ingest_forecast_events(db, uid, items, [{'role':'assistant', 'content':items[0]['source_quote']}]) == 0


def test_forecast_memory_partial_update_preserves_amount():
    from app.notes.extraction import _ingest_forecast_events
    from tests.forecast_fixture import FixtureDB, UID
    db = FixtureDB()
    first = {'label':'Our wedding', 'amount':6000, 'month':'2027-06', 'source_quote':'Wedding costs $6000 in June.'}
    second = {'label':'Wedding', 'amount':None, 'month':'2027-07', 'source_quote':'Our wedding is now in July.'}
    _ingest_forecast_events(db, UID, [first], [{'role':'user', 'content':first['source_quote']}])
    _ingest_forecast_events(db, UID, [second], [{'role':'user', 'content':second['source_quote']}])
    events = [n['provenance']['forecast_event'] for n in db.tables['user_notes'] if n.get('source') == 'chat_extraction']
    assert len(events) == 1
    assert events[0]['amount'] == 6000
    assert events[0]['month'] == '2027-07'


def test_distinct_same_label_events_and_cancellation():
    from app.notes.extraction import _ingest_forecast_events, _load_forecast_context
    from app.engine.forecast import build_assumptions
    from tests.forecast_fixture import FixtureDB, UID, TODAY
    db = FixtureDB()
    db.tables['user_notes'] = []
    for month in ['2027-03', '2027-08']:
        item = {'label':'Vacation', 'amount':2000, 'month':month, 'new_event':True, 'source_quote':f'Vacation in {month} costs $2000.'}
        _ingest_forecast_events(db, UID, [item], [{'role':'user', 'content':item['source_quote']}])
    assert len(db.tables['user_notes']) == 2
    first = db.tables['user_notes'][0]['id']
    assert first in _load_forecast_context(db, UID)
    item = {'label':'Vacation', 'existing_event_id':first, 'cancelled':True, 'source_quote':'Cancel the March vacation.'}
    _ingest_forecast_events(db, UID, [item], [{'role':'user', 'content':item['source_quote']}])
    assumptions = build_assumptions([], [], [], db.tables['user_notes'], today=TODAY)
    assert len(assumptions) == 1
    assert assumptions[0].month == '2027-08'


def test_build_prompt_includes_messages_and_context():
    p = _build_prompt(
        context_summary="user already prefers conservative advice",
        messages=[
            {"role": "user", "content": "I'd never tap my 401k early"},
            {"role": "assistant", "content": "Got it."},
        ],
    )
    assert "401k" in p
    assert "conservative advice" in p


@pytest.mark.asyncio
async def test_extract_for_user_inserts_preference_when_extractor_returns_one(monkeypatch):
    user_id = uuid4()
    fake_resp = MagicMock()
    fake_resp.text = json.dumps({
        "facts": [],
        "preferences": [{"content": "Won't tap 401k early", "tags": ["retirement"]}],
        "examples": [],
    })
    fake_gemini = MagicMock()
    fake_gemini.aio.models.generate_content = AsyncMock(return_value=fake_resp)

    inserted = []
    monkeypatch.setattr("app.notes.extraction.insert_note",
                       lambda db, new: inserted.append(new) or MagicMock(id=uuid4()))
    monkeypatch.setattr("app.notes.extraction.embed_text",
                       AsyncMock(return_value=[0.0] * 768))
    monkeypatch.setattr("app.notes.extraction.similarity_search",
                       lambda db, **kw: [])
    monkeypatch.setattr("app.notes.extraction._load_recent_messages",
                       lambda db, user_id, since: [
                           {"role": "user", "content": "I'd never tap my 401k early"},
                       ])
    monkeypatch.setattr("app.notes.extraction._load_context_summary",
                       lambda db, user_id: "")
    monkeypatch.setattr("app.notes.extraction._load_forecast_context",
                       lambda db, user_id: "")
    monkeypatch.setattr("app.notes.extraction._update_last_extracted",
                       lambda db, user_id: None)

    n = await extract_for_user(db=MagicMock(), gemini=fake_gemini, user_id=user_id)

    assert n == 1
    assert any("401k" in x.content for x in inserted)
    assert any("topic:retirement" in (x.tags or []) for x in inserted)


@pytest.mark.asyncio
async def test_ingest_examples_stores_embedding(monkeypatch):
    user_id = uuid4()
    fixed_embedding = [0.1, 0.2, 0.3]

    fake_gemini = MagicMock()

    inserted = []
    monkeypatch.setattr("app.notes.extraction.embed_text",
                        AsyncMock(return_value=fixed_embedding))
    monkeypatch.setattr("app.notes.extraction.score_importance",
                        AsyncMock(return_value=5))
    monkeypatch.setattr("app.notes.extraction.insert_note",
                        lambda db, new: inserted.append(new) or MagicMock(id=uuid4()))

    items = [{"content": "Advisor incorrectly classified rent as discretionary; it is fixed.", "tags": ["housing"]}]
    n = await _ingest_examples(db=MagicMock(), gemini=fake_gemini, user_id=user_id, items=items)

    assert n == 1
    assert len(inserted) == 1
    assert inserted[0].embedding is not None
    assert inserted[0].embedding == fixed_embedding
