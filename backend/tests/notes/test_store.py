import pytest

from app.notes.schema import NewNote, NoteKind, NoteSource
from app.notes.store import insert_note, get_note, retire_note, supersede_notes, similarity_search


@pytest.mark.integration
def test_insert_note_round_trip(supabase_admin_db, test_user):
    """Inserts a fact note and reads it back with all fields preserved."""
    uid, _ = test_user
    new = NewNote(
        user_id=uid,
        kind=NoteKind.FACT,
        content="Account abc nicknamed 'Emergency Cash'",
        tags=["entity:account:abc", "topic:cashflow"],
        entity_refs={"accounts": ["abc"]},
        source=NoteSource.ENTITY_EDIT,
        provenance={"field": "name", "before": "Old", "after": "Emergency Cash"},
    )

    inserted = insert_note(supabase_admin_db, new)

    assert inserted.id is not None
    assert inserted.kind == NoteKind.FACT
    assert inserted.tags == ["entity:account:abc", "topic:cashflow"]

    fetched = get_note(supabase_admin_db, inserted.id)
    assert fetched is not None
    assert fetched.content == new.content
    assert fetched.entity_refs == {"accounts": ["abc"]}


@pytest.mark.integration
def test_retire_note_sets_expires_at(supabase_admin_db, test_user):
    uid, _ = test_user
    new = NewNote(
        user_id=uid, kind=NoteKind.EXAMPLE, content="x",
        source=NoteSource.MESSAGE_FEEDBACK,
        provenance={"message_id": "m1", "label": "good_advice"},
    )
    inserted = insert_note(supabase_admin_db, new)

    retire_note(supabase_admin_db, inserted.id)

    row = supabase_admin_db.table("user_notes").select("expires_at").eq("id", str(inserted.id)).execute().data[0]
    assert row["expires_at"] is not None


@pytest.mark.integration
def test_supersede_marks_old_rows(supabase_admin_db, test_user):
    uid, _ = test_user
    a = insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.FACT, content="old",
        source=NoteSource.ENTITY_EDIT,
        tags=["entity:account:abc"],
        provenance={"field": "name"},
    ))
    b = insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.FACT, content="new",
        source=NoteSource.ENTITY_EDIT,
        tags=["entity:account:abc"],
        provenance={"field": "name"},
    ))

    supersede_notes(supabase_admin_db, old_ids=[a.id], new_id=b.id)

    a_row = supabase_admin_db.table("user_notes").select("superseded_by").eq("id", str(a.id)).execute().data[0]
    b_row = supabase_admin_db.table("user_notes").select("supersedes").eq("id", str(b.id)).execute().data[0]
    assert a_row["superseded_by"] == str(b.id)
    assert str(a.id) in b_row["supersedes"]


@pytest.mark.integration
def test_similarity_search_returns_closest_first(supabase_admin_db, test_user):
    uid, _ = test_user
    # Use anti-parallel vectors so cosine similarity actually distinguishes them.
    # All-equal-positive vectors (e.g. [0.1]*768 vs [0.9]*768) are colinear and
    # have identical cosine to any positive query — ordering would be undefined.
    near = [0.1] * 768
    far = [-0.1] * 768
    n1 = insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.PREFERENCE,
        content="never tap 401k",
        embedding=near,
        source=NoteSource.CHAT_EXTRACTION,
    ))
    n2 = insert_note(supabase_admin_db, NewNote(
        user_id=uid, kind=NoteKind.PREFERENCE,
        content="dining is non-negotiable",
        embedding=far,
        source=NoteSource.CHAT_EXTRACTION,
    ))

    query = [0.1] * 768
    hits = similarity_search(supabase_admin_db, user_id=uid, query_vec=query, limit=2, threshold=0.5)

    # n1 is parallel to query (cosine ≈ 1), n2 is anti-parallel (cosine ≈ -1)
    # so n2 is excluded by threshold and only n1 should remain.
    assert len(hits) == 1
    assert hits[0].id == n1.id
