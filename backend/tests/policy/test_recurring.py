"""Unit tests for app.policy.recurring — derive_from_rejection + the
filter that drops rejected keywords from new proposals. DB is mocked."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.policy import recurring as pr
from app.policy.schema import Domain, Override


def _override(key: str = "reject:netflix", value: dict | None = None) -> Override:
    now = datetime.now(timezone.utc)
    return Override(
        id=uuid4(), user_id=uuid4(), domain=Domain.RECURRING,
        key=key, value=value or {"rejected": True},
        strength=1, created_at=now, last_reinforced_at=now,
    )


# ---- derive_from_rejection ------------------------------------------------


def test_derive_writes_reject_policy_on_first_call():
    """Single explicit user_rejected action is enough — they took deliberate
    action saying 'this is not recurring.'"""
    db = MagicMock()
    with patch("app.policy.recurring.policy_store.insert_or_reinforce",
               return_value=_override()) as write:
        out = pr.derive_from_rejection(
            db, user_id=uuid4(), keyword="Netflix",
        )

    assert out is True
    write.assert_called_once()
    kwargs = write.call_args.kwargs
    assert kwargs["domain"] == Domain.RECURRING
    assert kwargs["key"] == "reject:netflix"
    assert kwargs["value"] == {"rejected": True}


def test_derive_returns_false_for_empty_keyword():
    db = MagicMock()
    out = pr.derive_from_rejection(db, user_id=uuid4(), keyword="")
    assert out is False


def test_derive_swallows_write_failure():
    db = MagicMock()
    with patch("app.policy.recurring.policy_store.insert_or_reinforce",
               side_effect=RuntimeError("policy table missing")):
        out = pr.derive_from_rejection(
            db, user_id=uuid4(), keyword="Netflix",
        )
    assert out is False


# ---- filter_rejected_keywords ---------------------------------------------


def test_filter_drops_rejected_keywords():
    """Returns the SUBSET that is NOT rejected. Detector then only
    surfaces these clusters to the user."""
    keywords = ["Netflix", "Spotify", "NETFLIX 2024"]
    with patch("app.policy.recurring.policy_store.list_for_user",
               return_value=[_override(key="reject:netflix")]):
        out = pr.filter_rejected_keywords(
            MagicMock(), user_id=uuid4(), keywords=keywords,
        )
    # Only Spotify survives; both Netflix-shapes are filtered.
    assert out == {"Spotify"}


def test_filter_returns_all_when_no_policies():
    with patch("app.policy.recurring.policy_store.list_for_user", return_value=[]):
        out = pr.filter_rejected_keywords(
            MagicMock(), user_id=uuid4(), keywords=["Netflix", "Spotify"],
        )
    assert out == {"Netflix", "Spotify"}


def test_filter_returns_all_on_lookup_failure():
    """Engine degrades gracefully — broken policy read returns all keywords
    so the detector still surfaces clusters (unbiased fallback)."""
    keywords = ["Netflix", "Spotify"]
    with patch("app.policy.recurring.policy_store.list_for_user",
               side_effect=RuntimeError("DB down")):
        out = pr.filter_rejected_keywords(
            MagicMock(), user_id=uuid4(), keywords=keywords,
        )
    assert out == set(keywords)


def test_filter_ignores_policies_without_rejected_flag():
    """Only policies with value.rejected=True are honored. Other recurring-
    domain policy shapes (future expansion) are ignored by this filter."""
    irrelevant_policy = _override(
        key="boost:netflix", value={"some_other_flag": True},
    )
    with patch("app.policy.recurring.policy_store.list_for_user",
               return_value=[irrelevant_policy]):
        out = pr.filter_rejected_keywords(
            MagicMock(), user_id=uuid4(), keywords=["Netflix"],
        )
    assert out == {"Netflix"}


def test_filter_handles_empty_keywords():
    with patch("app.policy.recurring.policy_store.list_for_user", return_value=[]):
        out = pr.filter_rejected_keywords(
            MagicMock(), user_id=uuid4(), keywords=[],
        )
    assert out == set()


def test_filter_keeps_keywords_that_normalize_to_empty():
    """A keyword that normalizes to empty (all numeric / punctuation) can't
    match any reject:<norm> key — keep it rather than drop it."""
    with patch("app.policy.recurring.policy_store.list_for_user",
               return_value=[_override(key="reject:netflix")]):
        out = pr.filter_rejected_keywords(
            MagicMock(), user_id=uuid4(), keywords=["###"],
        )
    assert out == {"###"}
