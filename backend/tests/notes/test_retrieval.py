import pytest
from uuid import uuid4

from app.notes.schema import NewNote, NoteKind, NoteSource
from app.notes.store import insert_note, retrieve_notes


@pytest.mark.integration
def test_retrieve_notes_filters_facts_by_scope_tags(supabase_admin_db, test_user):
    uid, _ = test_user
    insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.FACT, content="account abc renamed",
        tags=["entity:account:abc"], source=NoteSource.ENTITY_EDIT,
    ))
    insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.FACT, content="goal xyz target updated",
        tags=["entity:goal:xyz"], source=NoteSource.ENTITY_EDIT,
    ))

    out = retrieve_notes(
        supabase_admin_db, user_id=uid,
        scope_tags=["entity:account:abc", "entity:profile:u1"],
        query_text=None,
    )
    contents = [n.content for n in out]
    assert "account abc renamed" in contents
    assert "goal xyz target updated" not in contents


@pytest.mark.integration
def test_retrieve_notes_always_injects_high_strength_preferences(supabase_admin_db, test_user):
    uid, _ = test_user
    insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.PREFERENCE,
        content="never tap 401k", strength=5,
        source=NoteSource.CHAT_EXTRACTION,
        embedding=[0.0] * 768,
    ))
    out = retrieve_notes(
        supabase_admin_db, user_id=uid,
        scope_tags=[], query_text=None,
    )
    assert any(n.content == "never tap 401k" for n in out)


@pytest.mark.integration
def test_retrieve_notes_excludes_superseded_and_expired(supabase_admin_db, test_user):
    from app.notes.store import retire_note, supersede_notes
    uid, _ = test_user
    a = insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.FACT, content="old",
        tags=["entity:account:abc"], source=NoteSource.ENTITY_EDIT,
    ))
    b = insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.FACT, content="new",
        tags=["entity:account:abc"], source=NoteSource.ENTITY_EDIT,
    ))
    supersede_notes(supabase_admin_db, old_ids=[a.id], new_id=b.id)

    expired = insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.FACT, content="retired",
        tags=["entity:account:abc"], source=NoteSource.ENTITY_EDIT,
    ))
    retire_note(supabase_admin_db, expired.id)

    out = retrieve_notes(
        supabase_admin_db, user_id=uid,
        scope_tags=["entity:account:abc"], query_text=None,
    )
    contents = [n.content for n in out]
    assert "new" in contents
    assert "old" not in contents
    assert "retired" not in contents
