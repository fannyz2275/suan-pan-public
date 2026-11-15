"""Unit tests for app.policy.categorize — promotion threshold, apply path,
key normalization, failure-mode resilience. DB is a MagicMock; the module
is intentionally pure logic plus thin Supabase calls."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.policy import categorize as cat
from app.policy.schema import Domain, Override


def _txn(description: str, category: str | None = "Food") -> dict:
    return {"id": str(uuid4()), "description": description, "category": category}


def _override(category: str = "Food", strength: int = 1) -> Override:
    now = datetime.now(timezone.utc)
    return Override(
        id=uuid4(), user_id=uuid4(), domain=Domain.CATEGORIZE,
        key=f"description:starbucks", value={"category": category},
        strength=strength, created_at=now, last_reinforced_at=now,
    )


def _mock_txn_scan(rows: list[dict]) -> MagicMock:
    db = MagicMock()
    chain = (
        db.table.return_value.select.return_value
        .eq.return_value.eq.return_value.limit.return_value
    )
    chain.execute.return_value = SimpleNamespace(data=rows)
    return db


# ---- _normalized_or_none ---------------------------------------------------


def test_normalized_or_none_strips_punct_and_digits():
    """normalize_description (reused from engine/recurring) strips punct +
    numbers + dates. categorize policy keys must match recurring's
    normalization so the two layers see the same description."""
    assert cat._normalized_or_none("STARBUCKS #1234 SEATTLE 2026-04-28") == "starbucks seattle"


def test_normalized_or_none_handles_empty():
    assert cat._normalized_or_none("") is None
    assert cat._normalized_or_none(None) is None
    # All-noise input → None
    assert cat._normalized_or_none("###") is None


# ---- derive_from_correction ------------------------------------------------


def test_derive_returns_false_below_threshold():
    """One historical match (the txn the user just fixed) does NOT promote.
    Threshold is 2 to avoid one-off accidental corrections becoming sticky."""
    db = _mock_txn_scan([_txn("Starbucks #001", "Food")])

    with patch("app.policy.categorize.policy_store.insert_or_reinforce") as write:
        out = cat.derive_from_correction(
            db, user_id=uuid4(), description="Starbucks #001", new_category="Food",
        )

    assert out is False
    write.assert_not_called()


def test_derive_promotes_at_threshold():
    """Two matching txns (current + one prior) crosses the two-strike rule
    and writes the policy."""
    db = _mock_txn_scan([
        _txn("Starbucks #001", "Food"),
        _txn("Starbucks #002", "Food"),
    ])

    with patch("app.policy.categorize.policy_store.insert_or_reinforce",
               return_value=_override()) as write:
        out = cat.derive_from_correction(
            db, user_id=uuid4(), description="Starbucks #002", new_category="Food",
        )

    assert out is True
    write.assert_called_once()
    kwargs = write.call_args.kwargs
    assert kwargs["domain"] == Domain.CATEGORIZE
    assert kwargs["key"] == "description:starbucks"
    assert kwargs["value"] == {"category": "Food"}


def test_derive_only_counts_matching_normalized_descriptions():
    """Different store names DON'T accumulate against the same key — only
    same-normalized-description rows count."""
    db = _mock_txn_scan([
        _txn("Starbucks #001", "Food"),
        _txn("Whole Foods 405", "Food"),  # different normalized key
        _txn("Whole Foods 901", "Food"),
    ])

    with patch("app.policy.categorize.policy_store.insert_or_reinforce") as write:
        out = cat.derive_from_correction(
            db, user_id=uuid4(), description="Starbucks #001", new_category="Food",
        )

    # Only one Starbucks-normalized row exists → below threshold
    assert out is False
    write.assert_not_called()


def test_derive_swallows_db_failure():
    db = MagicMock()
    db.table.side_effect = RuntimeError("DB down")

    out = cat.derive_from_correction(
        db, user_id=uuid4(), description="Starbucks", new_category="Food",
    )

    assert out is False  # caller's correction succeeded; only side effect dropped


def test_derive_swallows_policy_write_failure():
    db = _mock_txn_scan([_txn("a", "Food"), _txn("a", "Food")])  # threshold met

    with patch("app.policy.categorize.policy_store.insert_or_reinforce",
               side_effect=RuntimeError("policy table missing")):
        out = cat.derive_from_correction(
            db, user_id=uuid4(), description="a", new_category="Food",
        )

    assert out is False


def test_derive_with_empty_description_is_noop():
    db = MagicMock()
    out = cat.derive_from_correction(
        db, user_id=uuid4(), description="", new_category="Food",
    )
    assert out is False
    db.table.assert_not_called()


# ---- apply -----------------------------------------------------------------


def test_apply_returns_default_when_no_policy():
    db = MagicMock()
    with patch("app.policy.categorize.policy_store.lookup", return_value=None):
        out = cat.apply(
            db, user_id=uuid4(), description="Starbucks", default_category="Shopping",
        )
    assert out == "Shopping"


def test_apply_returns_override_category_when_policy_exists():
    db = MagicMock()
    with patch("app.policy.categorize.policy_store.lookup",
               return_value=_override(category="Food")):
        out = cat.apply(
            db, user_id=uuid4(), description="Starbucks #1234",
            default_category="Shopping",
        )
    assert out == "Food"


def test_apply_returns_default_on_lookup_failure():
    db = MagicMock()
    with patch("app.policy.categorize.policy_store.lookup",
               side_effect=RuntimeError("DB down")):
        out = cat.apply(
            db, user_id=uuid4(), description="Starbucks", default_category="Shopping",
        )
    assert out == "Shopping"  # never raises; engine sees default


def test_apply_returns_default_when_description_normalizes_to_empty():
    db = MagicMock()
    out = cat.apply(
        db, user_id=uuid4(), description="###", default_category="Other",
    )
    assert out == "Other"


def test_apply_falls_back_when_policy_value_missing_category_key():
    """A corrupt policy row (missing 'category' key in value JSONB) shouldn't
    return None — fall back to the default."""
    bad_override = _override()
    bad_override.value = {}  # corrupted shape

    db = MagicMock()
    with patch("app.policy.categorize.policy_store.lookup", return_value=bad_override):
        out = cat.apply(
            db, user_id=uuid4(), description="Starbucks", default_category="Shopping",
        )
    assert out == "Shopping"


# ---- Key derivation contract ----------------------------------------------


def test_key_for_uses_description_prefix_convention():
    """The 'description:<normalized>' key shape is what the policy table
    stores. If this changes, the migration's example doc is wrong AND any
    other domain that wants to share keys with categorize would drift."""
    assert cat._key_for("starbucks") == "description:starbucks"
