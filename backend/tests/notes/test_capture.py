import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from app.notes.capture import emit_fact_from_edit, _diff_fields, _format_diff_template


def test_diff_fields_returns_changed_only():
    before = {"name": "Old", "balance": 100, "type": "checking"}
    after = {"name": "New", "balance": 100, "type": "checking"}
    assert _diff_fields(before, after) == [("name", "Old", "New")]


def test_format_diff_template_for_numeric_field():
    msg = _format_diff_template("account", "abc", "balance", 100, 250)
    assert "account" in msg.lower()
    assert "100" in msg
    assert "250" in msg


@pytest.mark.asyncio
async def test_emit_fact_from_edit_inserts_fact_note(monkeypatch):
    user_id = uuid4()
    inserted_payloads = []

    def fake_insert(db, new):
        inserted_payloads.append(new)
        return MagicMock(id=uuid4())

    def fake_supersede(db, *, old_ids, new_id):
        pass

    def fake_find_existing(db, *, user_id, entity_kind, entity_id, field):
        return []

    monkeypatch.setattr("app.notes.capture.insert_note", fake_insert)
    monkeypatch.setattr("app.notes.capture.supersede_notes", fake_supersede)
    monkeypatch.setattr("app.notes.capture._find_existing_facts", fake_find_existing)

    await emit_fact_from_edit(
        db=MagicMock(),
        gemini=MagicMock(),
        user_id=user_id,
        entity_kind="account",
        entity_id="abc",
        before={"name": "Old"},
        after={"name": "New"},
    )

    assert len(inserted_payloads) == 1
    n = inserted_payloads[0]
    assert n.kind.value == "fact"
    assert "entity:account:abc" in n.tags
    assert n.entity_refs == {"accounts": ["abc"]}
    assert n.provenance["field"] == "name"


from app.notes.capture import emit_from_feedback


@pytest.mark.asyncio
async def test_helpfulness_is_not_verified_numerical_accuracy(monkeypatch):
    inserted = []
    monkeypatch.setattr("app.notes.capture.insert_note", lambda db, new: inserted.append(new) or MagicMock(id=uuid4()))
    monkeypatch.setattr("app.notes.capture._has_live_feedback_note", lambda *a, **kw: False)
    monkeypatch.setattr("app.notes.compaction.prune_examples_for_pattern", lambda *a, **kw: None)
    await emit_from_feedback(db=MagicMock(), gemini=None, user_id=uuid4(), message_id="m", session_id="s",
                             user_message_text="Question", assistant_message_text="Answer", labels={"helpful": True, "too_technical": True})
    assert {n.provenance["label"] for n in inserted} == {"helpful", "too_technical"}
    assert "not verification" in inserted[0].content


@pytest.mark.asyncio
async def test_emit_from_feedback_positive_label_creates_confirmed_example(monkeypatch):
    user_id = uuid4()
    inserted = []
    monkeypatch.setattr("app.notes.capture.insert_note",
                       lambda db, new: inserted.append(new) or MagicMock(id=uuid4()))
    monkeypatch.setattr("app.notes.capture.retire_existing_feedback_note",
                       lambda *a, **kw: None)
    monkeypatch.setattr("app.notes.capture._has_live_feedback_note",
                       lambda *a, **kw: False)

    await emit_from_feedback(
        db=MagicMock(),
        gemini=None,  # score_importance handles None -> DEFAULT_IMPORTANCE
        user_id=user_id,
        message_id="m1",
        session_id="s1",
        user_message_text="What about my goals?",
        assistant_message_text="Here are your goals: ...",
        labels={"good_advice": True, "bad_advice": False, "off_topic": False,
                "on_topic": False, "accurate_numbers": False, "inaccurate_numbers": False},
    )

    assert len(inserted) == 1
    n = inserted[0]
    assert "topic:advisor-confirmed" in n.tags
    assert n.provenance["label"] == "good_advice"
    assert n.provenance["message_id"] == "m1"


@pytest.mark.asyncio
async def test_emit_from_feedback_false_label_retires_existing(monkeypatch):
    user_id = uuid4()
    retired = []
    monkeypatch.setattr("app.notes.capture.insert_note",
                       lambda db, new: MagicMock(id=uuid4()))
    monkeypatch.setattr("app.notes.capture.retire_existing_feedback_note",
                       lambda db, *, user_id, message_id, label: retired.append((message_id, label)))
    monkeypatch.setattr("app.notes.capture._has_live_feedback_note",
                       lambda *a, **kw: False)

    await emit_from_feedback(
        db=MagicMock(),
        gemini=None,
        user_id=user_id,
        message_id="m1",
        session_id="s1",
        user_message_text="x",
        assistant_message_text="y",
        labels={"good_advice": False, "bad_advice": True, "off_topic": False,
                "on_topic": False, "accurate_numbers": False, "inaccurate_numbers": False},
    )

    # bad_advice is True: insert; the others (False) trigger retire
    assert ("m1", "good_advice") in retired
    assert ("m1", "off_topic") in retired


@pytest.mark.asyncio
async def test_emit_from_feedback_idempotent_when_live_note_exists(monkeypatch):
    """If a live note already exists for (msg, label), True-toggle is a no-op."""
    user_id = uuid4()
    inserted = []
    monkeypatch.setattr("app.notes.capture.insert_note",
                       lambda db, new: inserted.append(new) or MagicMock(id=uuid4()))
    monkeypatch.setattr("app.notes.capture.retire_existing_feedback_note",
                       lambda *a, **kw: None)
    # Simulate "live note already exists for good_advice on m1"
    def fake_has_live(db, *, user_id, message_id, label):
        return label == "good_advice" and message_id == "m1"
    monkeypatch.setattr("app.notes.capture._has_live_feedback_note", fake_has_live)

    await emit_from_feedback(
        db=MagicMock(), gemini=None, user_id=user_id,
        message_id="m1", session_id="s1",
        user_message_text="x", assistant_message_text="y",
        labels={"good_advice": True, "accurate_numbers": True,
                "bad_advice": False, "off_topic": False,
                "on_topic": False, "inaccurate_numbers": False},
    )

    # Only accurate_numbers (no live note) inserts; good_advice is no-op'd
    assert len(inserted) == 1
    assert inserted[0].provenance["label"] == "accurate_numbers"
