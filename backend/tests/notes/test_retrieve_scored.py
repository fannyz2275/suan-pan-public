"""Unit tests for the pure-Python portions of retrieve_scored.

These cover the math: normalization edge cases, recency decay shape, MMR
behavior, cosine. Full end-to-end against Supabase is a separate integration
test below.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.notes.schema import DEFAULT_IMPORTANCE
from app.notes.scoring import (
    DECAY_LAMBDA,
    RECENCY_HALF_LIFE_HOURS,
    compute_raw_scores,
    cosine,
    min_max_normalize,
    mmr_select,
    row_embedding,
)


# Aliases preserved so the test bodies continue to read like algorithm tests
# rather than module-path tests.
_compute_raw_scores = compute_raw_scores
_cosine = cosine
_min_max_normalize = min_max_normalize
_mmr_select = mmr_select
_row_embedding = row_embedding


# ---- Recency decay --------------------------------------------------------


def test_decay_lambda_yields_half_at_90_days():
    """ln(2) / (90·24h) — recency should be exactly 0.5 at the half-life."""
    half_life_recency = math.exp(-DECAY_LAMBDA * RECENCY_HALF_LIFE_HOURS)
    assert abs(half_life_recency - 0.5) < 1e-9


def test_compute_raw_scores_recency_now_is_one():
    now = datetime.now(timezone.utc)
    row = {
        "cosine_similarity": 0.42,
        "last_accessed_at": now,
        "importance": 7,
    }
    raw = _compute_raw_scores(row, query_vec=[0.1] * 768, now=now)
    assert raw["rec"] == pytest.approx(1.0, abs=1e-6)
    assert raw["rel"] == pytest.approx(0.42)
    assert raw["imp"] == pytest.approx(0.7)


def test_compute_raw_scores_recency_decays_over_time():
    now = datetime.now(timezone.utc)
    row = {
        "cosine_similarity": 0.5,
        "last_accessed_at": (now - timedelta(days=90)).isoformat(),
        "importance": 5,
    }
    raw = _compute_raw_scores(row, query_vec=[0.1] * 768, now=now)
    # 90d half-life → 0.5
    assert raw["rec"] == pytest.approx(0.5, abs=1e-3)


def test_compute_raw_scores_falls_back_to_created_at():
    now = datetime.now(timezone.utc)
    row = {
        "cosine_similarity": 0.5,
        "created_at": now.isoformat(),
        "importance": 5,
    }
    raw = _compute_raw_scores(row, query_vec=[0.1] * 768, now=now)
    assert raw["rec"] == pytest.approx(1.0, abs=1e-6)


def test_compute_raw_scores_handles_missing_importance():
    now = datetime.now(timezone.utc)
    row = {"cosine_similarity": 0.5, "last_accessed_at": now}
    raw = _compute_raw_scores(row, query_vec=[0.1] * 768, now=now)
    assert raw["imp"] == DEFAULT_IMPORTANCE / 10


def test_compute_raw_scores_no_query_vec_zeros_relevancy():
    """When the user message couldn't be embedded, relevance is 0 — only
    recency and importance pull notes into the top-K."""
    now = datetime.now(timezone.utc)
    row = {"cosine_similarity": 0.9, "last_accessed_at": now, "importance": 10}
    raw = _compute_raw_scores(row, query_vec=None, now=now)
    assert raw["rel"] == 0.0


# ---- Normalization --------------------------------------------------------


def test_normalize_empty_pool():
    assert _min_max_normalize([]) == []


def test_normalize_single_candidate_returns_neutral():
    """Pool size 1 carries no signal in any axis — return 0.5 across the
    board, consistent with the constant-axis tie-break. Returning 1.0 would
    inflate a stale singleton to a final score of 1.0 regardless of its
    actual recency or importance."""
    out = _min_max_normalize([{"rel": 0.3, "rec": 0.4, "imp": 0.5}])
    assert out == [{"rel": 0.5, "rec": 0.5, "imp": 0.5}]


def test_normalize_all_equal_axis_clamps_to_half():
    """If every candidate has the same value on an axis, that axis carries no
    signal — emit 0.5 for everyone (neutral contribution to the weighted sum)."""
    raw = [
        {"rel": 0.5, "rec": 0.2, "imp": 0.3},
        {"rel": 0.5, "rec": 0.8, "imp": 0.7},
        {"rel": 0.5, "rec": 0.5, "imp": 0.5},
    ]
    out = _min_max_normalize(raw)
    # rel axis is constant → all 0.5
    assert all(o["rel"] == 0.5 for o in out)
    # rec / imp got real spread → still normalized to [0,1]
    assert max(o["rec"] for o in out) == 1.0
    assert min(o["rec"] for o in out) == 0.0


def test_normalize_min_max_per_axis():
    raw = [
        {"rel": 0.10, "rec": 1.00, "imp": 0.20},
        {"rel": 0.50, "rec": 0.50, "imp": 0.60},
        {"rel": 0.90, "rec": 0.10, "imp": 1.00},
    ]
    out = _min_max_normalize(raw)
    # First row: rel min, rec max, imp min
    assert out[0]["rel"] == pytest.approx(0.0)
    assert out[0]["rec"] == pytest.approx(1.0)
    assert out[0]["imp"] == pytest.approx(0.0)
    # Last row: rel max, rec min, imp max
    assert out[2]["rel"] == pytest.approx(1.0)
    assert out[2]["rec"] == pytest.approx(0.0)
    assert out[2]["imp"] == pytest.approx(1.0)


# ---- Cosine ---------------------------------------------------------------


def test_cosine_parallel_vectors():
    assert _cosine([1.0, 0.0], [2.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_anti_parallel_vectors():
    assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_handles_zero_vector():
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert _cosine([], [1.0]) == 0.0


# ---- MMR ------------------------------------------------------------------


def _ordered_pair(emb, score, rel=None):
    """Build the (row, raw, composite_score) triplet shape that mmr_select consumes.

    `rel` defaults to `score` so that the first MMR pick (which uses raw
    relevancy as its tiebreak) matches the composite-top in these synthetic
    pools — mirrors the real pipeline where relevance dominates the score.
    Pass an explicit `rel` only when the test needs to drive a relevance/
    composite divergence.
    """
    raw = {"rel": score if rel is None else rel, "rec": 0.0, "imp": 0.0}
    return ({"embedding": emb}, raw, score)


def test_mmr_empty_pool_returns_empty():
    assert _mmr_select(ordered=[], query_vec=[0.1], top_k=5, lam=0.7) == []


def test_mmr_top_k_caps_at_pool_size():
    pool = [_ordered_pair([1.0, 0.0], 0.5)]
    out = _mmr_select(ordered=pool, query_vec=[1.0, 0.0], top_k=10, lam=0.7)
    assert out == [0]


def test_mmr_picks_diverse_over_near_duplicate_when_scores_close():
    """Three candidates: top-A, near-clone-A', diverse-B with a comparable
    score. λ=0.7 should pick A first; for slot two, B's diversity bonus
    overcomes A's slight score edge.

    Score math at slot two with λ=0.7:
      A':  0.7 * 0.93 - 0.3 * cos([.99,.01],[1,0])  ≈ 0.651 - 0.300 = 0.351
      B :  0.7 * 0.75 - 0.3 * cos([0,1],[1,0])      = 0.525 - 0.000 = 0.525
    """
    pool = [
        _ordered_pair([1.0, 0.0], 0.95),    # A
        _ordered_pair([0.99, 0.01], 0.93),  # A' near-clone
        _ordered_pair([0.0, 1.0], 0.75),    # B orthogonal, comparable score
    ]
    out = _mmr_select(ordered=pool, query_vec=[1.0, 0.0], top_k=2, lam=0.7)
    assert out[0] == 0
    assert out[1] == 2


def test_mmr_keeps_near_duplicate_when_score_gap_is_large():
    """Default λ=0.7 is relevance-leaning. A near-clone with much higher score
    than the diverse alternative still wins — by design (Park §4.2)."""
    pool = [
        _ordered_pair([1.0, 0.0], 0.95),    # A
        _ordered_pair([0.99, 0.01], 0.93),  # A' near-clone, only 0.02 below
        _ordered_pair([0.0, 1.0], 0.40),    # B orthogonal but much lower
    ]
    out = _mmr_select(ordered=pool, query_vec=[1.0, 0.0], top_k=2, lam=0.7)
    assert out[0] == 0
    assert out[1] == 1  # near-clone wins despite poor diversity


def test_mmr_first_pick_uses_raw_relevancy_not_composite_score():
    """Regression: MMR's first selection must maximize raw relevancy, not the
    composite score. With no priors selected, max_sim is 0 so the diversity
    term is moot — picking the composite-top can promote a stale-but-recent
    note over a genuinely relevant one.

    Pool here: the composite-top has low actual relevance (its score is high
    only because of recency+importance contributions); a different candidate
    has the highest raw relevance. MMR should pick the latter first.
    """
    pool = [
        # composite=0.95 but rel=0.10 (boosted by hypothetical recency/importance)
        _ordered_pair([1.0, 0.0], score=0.95, rel=0.10),
        # composite=0.70 but rel=0.90 — the genuinely relevant candidate
        _ordered_pair([0.0, 1.0], score=0.70, rel=0.90),
    ]
    out = _mmr_select(ordered=pool, query_vec=[0.0, 1.0], top_k=1, lam=0.7)
    assert out == [1]


def test_mmr_low_lambda_prefers_diversity():
    """With λ=0.3 the diversity term dominates — the near-clone is dropped
    even when its score is slightly higher."""
    pool = [
        _ordered_pair([1.0, 0.0], 0.95),
        _ordered_pair([0.99, 0.01], 0.93),
        _ordered_pair([0.0, 1.0], 0.40),
    ]
    out = _mmr_select(ordered=pool, query_vec=[1.0, 0.0], top_k=2, lam=0.3)
    assert out[0] == 0
    assert out[1] == 2  # diverse B wins under heavy diversity weight


def test_mmr_falls_back_to_relevance_when_no_embedding():
    pool = [
        _ordered_pair(None, 0.9),
        _ordered_pair(None, 0.7),
        _ordered_pair(None, 0.5),
    ]
    out = _mmr_select(ordered=pool, query_vec=None, top_k=2, lam=0.7)
    # No embeddings → MMR collapses to pure score order
    assert out == [0, 1]


# ---- Embedding coercion ---------------------------------------------------


def test_row_embedding_handles_string_form():
    # pgvector wire format comes back as JSON string in some clients.
    row = {"embedding": "[0.1, 0.2, 0.3]"}
    assert _row_embedding(row) == [0.1, 0.2, 0.3]


def test_row_embedding_handles_list_form():
    row = {"embedding": [0.1, 0.2, 0.3]}
    assert _row_embedding(row) == [0.1, 0.2, 0.3]


def test_row_embedding_handles_none():
    assert _row_embedding({"embedding": None}) is None
    assert _row_embedding({}) is None


def test_row_embedding_tolerates_malformed_string():
    assert _row_embedding({"embedding": "not json"}) is None
