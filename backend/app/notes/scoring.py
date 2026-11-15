"""Tunable parameters + pure-Python helpers for Tier 3 scored retrieval.

Lives separately from `store.py` so that anyone tuning the scoring weights,
half-life, or MMR diversity can find them without scrolling past DB plumbing.
The helpers are all stateless and DB-free — the unit tests in
`tests/notes/test_retrieve_scored.py` exercise them directly.

Algorithm (Park et al. 2023, COLLA semantic-tier retrieval):
    score = W_RELEVANCY * relevancy
          + W_RECENCY   * recency
          + W_IMPORTANCE * importance
    components min-max normalized within the candidate pool first.
    Then MMR rerank top-N -> top-K for diversity (lambda = MMR_LAMBDA).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Optional

from app.notes.schema import DEFAULT_IMPORTANCE

# ---- Tuning constants -----------------------------------------------------

# Recency exponential decay tuned for 90-day half-life.
# lambda = ln(2) / (90 * 24h)
RECENCY_HALF_LIFE_HOURS = 90 * 24
DECAY_LAMBDA = math.log(2) / RECENCY_HALF_LIFE_HOURS

# Score-sum weights. Sum to 1.0. Tuned later per-domain if eval shows need.
W_RELEVANCY = 0.5
W_RECENCY = 0.2
W_IMPORTANCE = 0.3

# Candidate pool size before MMR; final K is the user-facing top.
DEFAULT_POOL_N = 20
DEFAULT_TOP_K = 5
TAG_BOOST_CAP = 10  # extra candidates injected by tag overlap

# MMR diversity weight. 1.0 -> pure relevance; 0.0 -> pure diversity.
MMR_LAMBDA = 0.7


# ---- Algorithmic helpers --------------------------------------------------


def compute_raw_scores(
    row: dict, query_vec: Optional[list[float]], now: datetime,
) -> dict:
    """Compute raw (un-normalized) relevancy / recency / importance for a row."""
    rel = float(row.get("cosine_similarity") or 0.0)
    if query_vec is None:
        rel = 0.0

    last_access_raw = row.get("last_accessed_at") or row.get("created_at")
    if isinstance(last_access_raw, str):
        last_access = datetime.fromisoformat(last_access_raw.replace("Z", "+00:00"))
    elif isinstance(last_access_raw, datetime):
        last_access = last_access_raw
    else:
        last_access = now
    if last_access.tzinfo is None:
        last_access = last_access.replace(tzinfo=timezone.utc)
    delta_hours = max(0.0, (now - last_access).total_seconds() / 3600.0)
    rec = math.exp(-DECAY_LAMBDA * delta_hours)

    imp_raw = row.get("importance")
    if imp_raw is None:
        imp_raw = DEFAULT_IMPORTANCE
    imp = max(1, min(10, int(imp_raw))) / 10.0

    return {"rel": rel, "rec": rec, "imp": imp}


def min_max_normalize(raw_list: list[dict]) -> list[dict]:
    """Per-axis min-max within the candidate pool.

    Edge cases:
      - empty pool -> []
      - single candidate -> all axes 0.5 (no signal in a 1-point distribution;
        matches the constant-axis tie-break below; avoids artificially
        inflating a stale singleton to score 1.0 across all axes).
      - constant axis (max == min) -> 0.5 for everyone on that axis.
    """
    if not raw_list:
        return []
    if len(raw_list) == 1:
        return [{"rel": 0.5, "rec": 0.5, "imp": 0.5}]

    out = [{} for _ in raw_list]
    for axis in ("rel", "rec", "imp"):
        vs = [r[axis] for r in raw_list]
        lo, hi = min(vs), max(vs)
        rng = hi - lo
        for d, r in zip(out, raw_list):
            d[axis] = 0.5 if rng <= 1e-9 else (r[axis] - lo) / rng
    return out


def mmr_select(
    *, ordered: list[tuple], query_vec: Optional[list[float]],
    top_k: int, lam: float,
) -> list[int]:
    """Greedy MMR. `ordered` is pre-sorted by composite score desc.
    Returns indices into `ordered`, length <= top_k.

    First pick maximizes raw relevancy (since max_sim is trivially 0 with
    no priors selected); subsequent picks balance relevance against the
    maximum cosine similarity to anything already selected.

    With no embeddings the diversity penalty is zero, so MMR collapses to
    the composite-score order.
    """
    if not ordered:
        return []
    n = min(top_k, len(ordered))

    selected: list[int] = []
    while len(selected) < n:
        best_i = None
        best_score = -math.inf
        for i in range(len(ordered)):
            if i in selected:
                continue
            cand_row, raw, composite = ordered[i]
            cand_emb = row_embedding(cand_row)

            # First pick: there's no diversity term, so the right pick is
            # the one with the highest raw relevancy (NOT the composite-top,
            # which conflates relevance with recency/importance).
            if not selected:
                mmr = raw["rel"]
            elif cand_emb is None:
                # No embedding for this candidate — skip the diversity term.
                mmr = composite
            else:
                max_sim = 0.0
                for j in selected:
                    sel_emb = row_embedding(ordered[j][0])
                    if sel_emb is None:
                        continue
                    sim = cosine(cand_emb, sel_emb)
                    if sim > max_sim:
                        max_sim = sim
                mmr = lam * composite - (1.0 - lam) * max_sim

            if mmr > best_score:
                best_score = mmr
                best_i = i
        if best_i is None:
            break
        selected.append(best_i)
    return selected


def row_embedding(row: dict) -> Optional[list[float]]:
    """Coerce a row's `embedding` field into a list of floats. None on miss."""
    emb = row.get("embedding")
    if emb is None:
        return None
    if isinstance(emb, str):
        try:
            return json.loads(emb)
        except Exception:
            return None
    if isinstance(emb, list):
        return emb
    return None


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 for any zero-norm input."""
    if not a or not b:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    denom = math.sqrt(na * nb)
    if denom <= 1e-12:
        return 0.0
    return dot / denom
