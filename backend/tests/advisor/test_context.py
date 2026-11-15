"""Unit tests for app.advisor.context — Tier 1/2/3 builders + orchestrator.

Pure-Python where possible; DB and Gemini are mocked for the rest. End-to-end
integration against Supabase is out of scope here — tested in PR #3 cutover.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.advisor.context import (
    IDENTITY_IMPORTANCE_FLOOR,
    IDENTITY_PREF_LIMIT,
    LIVE_GOAL_CAP,
    TIER3_TOP_K,
    TRIVIAL_MAX_LEN,
    _render_goals,
    _render_pending,
    _summarize_profile_one_liner,
    _truncate,
    build_financial_context,
    build_identity_block,
    build_live_state_block,
    build_retrieved_memory_block,
    is_trivial_message,
)
from app.notes.schema import Note, NoteKind, NoteSource, ScoredNote


# ---- _summarize_profile_one_liner -----------------------------------------


def test_summarize_profile_full():
    """One-liner is identity-only — no dollar amounts (the dollar-amount rule)."""
    out = _summarize_profile_one_liner({
        "age": 29, "employment_status": "employed",
        "dependents": 1, "region": "SF Bay Area",
    })
    assert "29yo" in out
    assert "employed" in out
    assert "1 dependent" in out
    assert "dependents" not in out  # singular form
    assert "SF Bay Area" in out
    # Income / expenses must NEVER appear in T1 — they belong to T2.
    assert "$" not in out
    assert "income" not in out
    assert "expense" not in out


def test_summarize_profile_pluralizes_dependents():
    out = _summarize_profile_one_liner({"age": 35, "dependents": 3})
    assert "3 dependents" in out


def test_summarize_profile_omits_unknown_employment():
    out = _summarize_profile_one_liner({"age": 29, "employment_status": "unknown"})
    assert "unknown" not in out


def test_summarize_profile_handles_empty():
    assert "incomplete" in _summarize_profile_one_liner({})


def test_summarize_profile_drops_legacy_dollar_fields():
    """Even if the profile dict still carries them (transitional read paths),
    the one-liner must ignore them."""
    out = _summarize_profile_one_liner({
        "age": 30,
        "annual_income": 999_999,
        "monthly_expenses": 88_888,
    })
    assert "$" not in out
    assert "30yo" in out


# ---- build_identity_block --------------------------------------------------


def _mock_anchor_query(rows: list[dict]) -> MagicMock:
    """Build a chained MagicMock that mimics the supabase-py select chain
    used by `_load_anchor_preferences`. Returns rows on .execute().

    Chain shape (must match the real query in context.py:_load_anchor_preferences):
      table → select → eq → eq → is_ → gte → order → order → limit → execute
    """
    db = MagicMock()
    chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value
        .is_.return_value.gte.return_value
        .order.return_value.order.return_value
        .limit.return_value
    )
    chain.execute.return_value = SimpleNamespace(data=rows)
    return db


def test_identity_block_includes_typed_profile_line():
    db = _mock_anchor_query([])
    profile = {
        "age": 29, "employment_status": "employed",
        "dependents": 1, "region": "SF Bay Area",
        "risk_tolerance_v2": 3, "time_horizon_v2": 5,
    }
    block, anchor_ids = build_identity_block(db, user_id=str(uuid4()), profile=profile)
    assert "USER IDENTITY" in block
    assert "29yo" in block
    # Scalar identity rendered with anchor sentence (Risk 3/5 (balanced) etc.)
    assert "Risk 3/5" in block
    assert "Horizon 5/5" in block
    assert anchor_ids == []


def test_identity_block_renders_anchor_preferences_and_returns_ids():
    rows = [
        {"id": "id-A", "content": "Won't tap 401k early under any circumstances.",
         "importance": 10, "last_accessed_at": None},
        {"id": "id-B", "content": "Prioritizes retirement over near-term lifestyle.",
         "importance": 9, "last_accessed_at": None},
        {"id": "id-C", "content": "Prefers data-heavy explanations.",
         "importance": 8, "last_accessed_at": None},
    ]
    db = _mock_anchor_query(rows)
    block, anchor_ids = build_identity_block(
        db, user_id=str(uuid4()), profile={"age": 30}
    )
    assert "Anchors:" in block
    assert "401k" in block
    assert "data-heavy" in block
    assert anchor_ids == ["id-A", "id-B", "id-C"]


def test_identity_block_caps_at_pref_limit():
    """Sort + cap is now done in the SQL query (.limit) — the test still
    asserts the contract: at most IDENTITY_PREF_LIMIT IDs come back."""
    rows = [
        {"id": f"id-{i}", "content": f"pref {i}", "importance": 10 - i,
         "last_accessed_at": None}
        for i in range(IDENTITY_PREF_LIMIT)
    ]
    db = _mock_anchor_query(rows)
    _, anchor_ids = build_identity_block(
        db, user_id=str(uuid4()), profile={"age": 30}
    )
    assert len(anchor_ids) == IDENTITY_PREF_LIMIT


def test_identity_block_swallows_db_failure():
    db = MagicMock()
    db.table.side_effect = RuntimeError("DB down")
    block, anchor_ids = build_identity_block(
        db, user_id=str(uuid4()), profile={"age": 29}
    )
    # Profile line still renders; no anchors emitted.
    assert "29yo" in block
    assert "Anchors:" not in block
    assert anchor_ids == []


# ---- build_live_state_block ------------------------------------------------


def _snapshot(**overrides):
    base = {
        "net_worth": 284500, "liquid_assets": 42100,
        "investment_assets": 215400, "non_current_assets": 27000,
    }
    base.update(overrides)
    return base


def test_live_state_renders_snapshot_one_liner():
    out = build_live_state_block(snapshot=_snapshot(), goals=[])
    assert "Net worth: $284,500" in out
    assert "liquid $42,100" in out
    assert "non-current $27,000" in out


def test_live_state_omits_pending_lines_when_zero():
    out = build_live_state_block(
        snapshot=_snapshot(), goals=[],
        pending_findings_count=0, pending_recurring_count=0,
        pending_transfer_reviews={"count_total": 0},
    )
    assert "Pending:" not in out


def test_live_state_renders_pending_counts_when_nonzero():
    out = build_live_state_block(
        snapshot=_snapshot(), goals=[],
        pending_findings_count=2, pending_recurring_count=1,
        pending_transfer_reviews={"count_total": 3},
    )
    assert "3 transfers to review" in out
    assert "2 findings" in out
    assert "1 unconfirmed recurring" in out


def test_live_state_caps_goals_and_orders_primary_first():
    goals = [
        {"name": "ord", "target_amount": 1000, "target_date": "2027-01-01",
         "current_progress": 100, "is_primary": False, "feasibility_score": 90, "status": "on_track"},
        {"name": "primary", "target_amount": 1000, "target_date": "2027-01-01",
         "current_progress": 100, "is_primary": True, "feasibility_score": 90, "status": "on_track"},
        {"name": "atrisk", "target_amount": 1000, "target_date": "2026-09-01",
         "current_progress": 100, "is_primary": False, "feasibility_score": 30, "status": "at_risk"},
    ]
    # Add LIVE_GOAL_CAP+3 dummies to force capping
    for i in range(LIVE_GOAL_CAP + 3):
        goals.append({
            "name": f"extra{i}", "target_amount": 1, "target_date": "2030-01-01",
            "current_progress": 0, "is_primary": False, "feasibility_score": 100, "status": "on_track",
        })
    out = build_live_state_block(snapshot=_snapshot(), goals=goals)
    assert f"Top {LIVE_GOAL_CAP} of {len(goals)}" in out
    # Primary listed first (after the count line)
    primary_pos = out.find("primary")
    atrisk_pos = out.find("atrisk")
    assert 0 < primary_pos < atrisk_pos


def test_live_state_includes_last_import():
    out = build_live_state_block(
        snapshot=_snapshot(), goals=[],
        last_import_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        last_import_count=47,
    )
    assert "Last import: 2026-04-28 (47 txns)" in out


def test_render_pending_collects_only_nonzero():
    bits = _render_pending({"count_total": 0}, 0, 5)
    assert bits == ["5 unconfirmed recurring"]


# ---- KPI line --------------------------------------------------------------


def _kpi_db(history_rows: list[dict] | None = None,
            txn_rows: list[dict] | None = None,
            account_rows: list[dict] | None = None) -> MagicMock:
    """Mock supabase that routes per-table queries to seeded rows.

    Mirrors the shape used in tests/engine/test_kpis.py so the KPI line
    renderer can be exercised through build_live_state_block without
    standing up a real DB.
    """
    table_rows = {
        "account_balance_history": history_rows or [],
        "transactions": txn_rows or [],
        "accounts": account_rows or [],
    }

    class _Q:
        def __init__(self, rows):
            self._rows = rows
        def select(self, *_a, **_kw): return self
        def eq(self, *_a, **_kw): return self
        def gte(self, *_a, **_kw): return self
        def lte(self, *_a, **_kw): return self
        def in_(self, *_a, **_kw): return self
        def order(self, *_a, **_kw): return self
        def limit(self, *_a, **_kw): return self
        def execute(self): return SimpleNamespace(data=list(self._rows))

    db = MagicMock()
    db.table.side_effect = lambda name: _Q(table_rows.get(name, []))
    return db


def test_live_state_emits_kpi_line_when_db_provided():
    """All four KPIs render n/a for a cold-start user (no transactions, no
    history, no investment accounts, no recurring outflow) — the line still
    appears so the LLM is told what's missing."""
    db = _kpi_db()
    out = build_live_state_block(
        db=db, user_id=str(uuid4()),
        snapshot=_snapshot(), goals=[],
    )
    assert "KPIs:" in out
    assert "Liquidity n/a" in out
    assert "Savings n/a" in out
    assert "NW yoy n/a" in out
    assert "Yield n/a" in out


def test_live_state_omits_kpi_line_without_db():
    """Legacy call sites (no db / user_id) still work; KPI line is just dropped."""
    out = build_live_state_block(snapshot=_snapshot(), goals=[])
    assert "KPIs:" not in out
    assert "Net worth:" in out


def test_live_state_kpi_line_swallows_engine_failure():
    """If the KPI engine raises, the line is dropped (best-effort) — the
    rest of the live state must still render."""
    db = MagicMock()
    db.table.side_effect = RuntimeError("DB explosion")
    out = build_live_state_block(
        db=db, user_id=str(uuid4()),
        snapshot=_snapshot(), goals=[],
    )
    assert "KPIs:" not in out
    assert "Net worth:" in out


def test_render_goals_marks_primary_with_star():
    out = _render_goals([
        {"name": "g", "target_amount": 100, "target_date": "2027-01-01",
         "current_progress": 50, "is_primary": True, "feasibility_score": 80,
         "status": "on_track"},
    ])
    assert "★" in out
    assert "50%" in out


# ---- build_retrieved_memory_block ------------------------------------------


def _scored_note(content: str, kind: NoteKind = NoteKind.PREFERENCE) -> ScoredNote:
    return ScoredNote(
        note=Note(
            id=uuid4(), user_id=uuid4(), kind=kind, content=content,
            tags=[], entity_refs={}, embedding=None,
            source=NoteSource.CHAT_EXTRACTION,
            provenance={}, strength=1, importance=8,
            last_accessed_at=None,
            supersedes=[], superseded_by=None, expires_at=None,
            created_at=datetime.now(timezone.utc),
        ),
        raw_relevancy=0.8, raw_recency=0.9, raw_importance=0.8,
        score=0.83,
    )


@pytest.mark.asyncio
async def test_retrieved_memory_block_empty_pool_returns_empty_string():
    db = MagicMock()
    gemini = MagicMock()
    with patch("app.advisor.context.embed_text",
               new=AsyncMock(return_value=[0.1] * 768)), \
         patch("app.advisor.context.retrieve_scored", return_value=[]):
        out = await build_retrieved_memory_block(
            db, gemini, user_id=uuid4(), query_text="hi",
            profile={"id": str(uuid4())}, accounts=[], goals=[],
        )
    assert out == ""


@pytest.mark.asyncio
async def test_retrieved_memory_block_renders_kind_tags():
    db = MagicMock()
    gemini = MagicMock()
    scored = [
        _scored_note("Joint with spouse", kind=NoteKind.FACT),
        _scored_note("Won't tap 401k", kind=NoteKind.PREFERENCE),
        _scored_note("Whole Foods is Food", kind=NoteKind.EXAMPLE),
    ]
    with patch("app.advisor.context.embed_text",
               new=AsyncMock(return_value=[0.1] * 768)), \
         patch("app.advisor.context.retrieve_scored", return_value=scored):
        out = await build_retrieved_memory_block(
            db, gemini, user_id=uuid4(), query_text="anything",
            profile={"id": str(uuid4())}, accounts=[], goals=[],
        )
    assert "RELEVANT TO THIS QUESTION" in out
    assert "[fact" in out
    assert "[pref" in out
    assert "[example" in out


@pytest.mark.asyncio
async def test_retrieved_memory_block_swallows_retrieve_failure():
    db = MagicMock()
    gemini = MagicMock()

    def boom(*a, **kw):
        raise RuntimeError("DB down")

    with patch("app.advisor.context.embed_text",
               new=AsyncMock(return_value=None)), \
         patch("app.advisor.context.retrieve_scored", side_effect=boom):
        out = await build_retrieved_memory_block(
            db, gemini, user_id=uuid4(), query_text="x",
            profile={"id": str(uuid4())}, accounts=[], goals=[],
        )
    assert out == ""


# ---- build_financial_context (orchestrator) -----------------------------


@pytest.mark.asyncio
async def test_v2_orchestrator_emits_all_section_delimiters():
    db = _mock_anchor_query([])
    gemini = MagicMock()
    profile = {"age": 30, "employment_status": "employed",
               "risk_tolerance_v2": 3, "time_horizon_v2": 5}
    with patch("app.advisor.context.embed_text",
               new=AsyncMock(return_value=None)), \
         patch("app.advisor.context.retrieve_scored", return_value=[]):
        out = await build_financial_context(
            db, gemini, user_id=uuid4(),
            profile=profile, snapshot=_snapshot(), goals=[],
            accounts=[], last_user_message="hello",
        )
    assert "Today's date:" in out
    assert "USER IDENTITY" in out
    assert "LIVE STATE" in out
    # Tier 3 section absent when retrieval is empty (avoids dead delimiters).
    assert "RELEVANT TO THIS QUESTION" not in out


@pytest.mark.asyncio
async def test_v2_orchestrator_excludes_anchor_ids_from_tier3():
    """Anchor preferences surfaced in Tier 1 must not also surface in Tier 3."""
    anchor_id = str(uuid4())
    db = _mock_anchor_query([{
        "id": anchor_id, "content": "anchor pref",
        "importance": 10, "last_accessed_at": None,
    }])
    gemini = MagicMock()
    captured_excludes = {}

    def fake_retrieve(db, *, user_id, query_vec, scope_tags, top_k, exclude_ids):
        captured_excludes["ids"] = [str(x) for x in exclude_ids]
        return []

    with patch("app.advisor.context.embed_text",
               new=AsyncMock(return_value=None)), \
         patch("app.advisor.context.retrieve_scored", side_effect=fake_retrieve):
        await build_financial_context(
            db, gemini, user_id=uuid4(),
            profile={"age": 30}, snapshot=_snapshot(), goals=[],
            accounts=[], last_user_message="hello",
        )
    assert anchor_id in captured_excludes["ids"]


# ---- Tier 0 sparse gate ----------------------------------------------------


@pytest.mark.parametrize("text", [
    "thanks", "Thanks!", "ok", "Okay.", "got it", "yep", "yes", "no",
    "sure", "cool", "great", "awesome", "makes sense", "interesting",
    "👍", "👎",
])
def test_is_trivial_message_acks(text):
    """Bare acks are trivial when there's no prior assistant question."""
    assert is_trivial_message(text, prev_assistant_msg=None) is True


def test_is_trivial_message_post_question_trap():
    """A short reply becomes substantive when responding to an assistant
    question — otherwise the advisor never gets the user's clarification
    answer in their context."""
    assert is_trivial_message(
        "yes", prev_assistant_msg="Should I include your spouse's income?"
    ) is False
    assert is_trivial_message(
        "no", prev_assistant_msg="Want me to break that down by month?"
    ) is False


def test_is_trivial_message_long_text_always_substantive():
    long_text = "x" * (TRIVIAL_MAX_LEN + 1)
    assert is_trivial_message(long_text, prev_assistant_msg=None) is False


def test_is_trivial_message_financial_token_overrides_trivial_form():
    """Even a 'cool' becomes substantive if it mentions $ or a goal."""
    assert is_trivial_message("cool, $200 saved", prev_assistant_msg=None) is False
    assert is_trivial_message("ok, my budget", prev_assistant_msg=None) is False
    assert is_trivial_message(
        "show last month", prev_assistant_msg=None
    ) is False


def test_is_trivial_message_first_turn_substantive_text():
    """First turn of a session: prev_assistant_msg is None. A non-trivial
    message ('what's my net worth?') stays substantive — only bare acks
    flip to trivial."""
    assert is_trivial_message(
        "what's my net worth?", prev_assistant_msg=None
    ) is False


def test_is_trivial_message_empty_input_is_substantive():
    """Empty / None input is treated as substantive — better to over-pay
    than under-retrieve on a malformed message."""
    assert is_trivial_message("", prev_assistant_msg=None) is False
    assert is_trivial_message(None, prev_assistant_msg=None) is False  # type: ignore


@pytest.mark.asyncio
async def test_v2_orchestrator_skips_tier3_for_trivial_message():
    """Regression for Tier 0: a 'thanks' turn must not invoke
    build_retrieved_memory_block — saves the embed + pgvector + MMR cost."""
    db = _mock_anchor_query([])
    gemini = MagicMock()
    profile = {"age": 30}

    with patch("app.advisor.context.build_retrieved_memory_block",
               new=AsyncMock(return_value="UNEXPECTED")) as retrieve_mock:
        out = await build_financial_context(
            db, gemini, user_id=uuid4(),
            profile=profile, snapshot=_snapshot(), goals=[],
            accounts=[], last_user_message="thanks",
            prev_assistant_msg="Here's your snapshot.",
        )

    retrieve_mock.assert_not_called()
    assert "RELEVANT TO THIS QUESTION" not in out
    # Tier 1 + Tier 2 still rendered
    assert "USER IDENTITY" in out
    assert "LIVE STATE" in out


@pytest.mark.asyncio
async def test_v2_orchestrator_runs_tier3_for_substantive_message():
    db = _mock_anchor_query([])
    gemini = MagicMock()

    with patch("app.advisor.context.build_retrieved_memory_block",
               new=AsyncMock(return_value="")) as retrieve_mock:
        await build_financial_context(
            db, gemini, user_id=uuid4(),
            profile={"age": 30}, snapshot=_snapshot(), goals=[],
            accounts=[], last_user_message="should I refinance my mortgage?",
            prev_assistant_msg=None,
        )

    retrieve_mock.assert_called_once()


# ---- _truncate -------------------------------------------------------------


def test_truncate_short_string_unchanged():
    assert _truncate("hello", 10) == "hello"


def test_truncate_long_string_appends_ellipsis():
    out = _truncate("a" * 50, 10)
    assert out.endswith("…")
    # Cap is the slice width; the appended "…" is one extra char, so output
    # length is n + 1. Tunable via NOTE_CHAR_CAP.
    assert len(out) == 11
