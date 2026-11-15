"""Unit tests for app.policy.transfers — derive_from_mark_external + the
filter that drops policy-marked txns from the pairing pool. DB is mocked."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.policy import transfers as pt
from app.policy.schema import Domain, Override


def _override(key: str = "external:venmo cashout", value: dict | None = None) -> Override:
    now = datetime.now(timezone.utc)
    return Override(
        id=uuid4(), user_id=uuid4(), domain=Domain.TRANSFERS,
        key=key, value=value or {"always_external": True},
        strength=1, created_at=now, last_reinforced_at=now,
    )


# ---- derive_from_mark_external --------------------------------------------


def test_derive_promotes_immediately_on_first_call():
    """Single explicit mark-external action is enough to write the policy.
    Higher threshold than categorize because the action is more deliberate."""
    db = MagicMock()
    with patch("app.policy.transfers.policy_store.insert_or_reinforce",
               return_value=_override()) as write:
        out = pt.derive_from_mark_external(
            db, user_id=uuid4(), description="Venmo Cashout 0001",
        )

    assert out is True
    write.assert_called_once()
    kwargs = write.call_args.kwargs
    assert kwargs["domain"] == Domain.TRANSFERS
    assert kwargs["key"] == "external:venmo cashout"  # normalized
    assert kwargs["value"] == {"always_external": True}


def test_derive_returns_false_for_empty_description():
    db = MagicMock()
    out = pt.derive_from_mark_external(db, user_id=uuid4(), description="")
    assert out is False


def test_derive_swallows_write_failure():
    db = MagicMock()
    with patch("app.policy.transfers.policy_store.insert_or_reinforce",
               side_effect=RuntimeError("policy table missing")):
        out = pt.derive_from_mark_external(
            db, user_id=uuid4(), description="Venmo",
        )
    assert out is False


# ---- filter_external_candidates -------------------------------------------


def test_filter_drops_candidates_matching_external_policy():
    """Match is on the FULL normalized description (the policy key), not a
    substring. 'Venmo Cashout 0001' normalizes to 'venmo cashout' (matches);
    'VENMO 9988' normalizes to 'venmo' (different key — kept). This means
    the user has to mark each distinct normalized variant external — by
    design, to avoid over-broad sticky exclusions."""
    candidates = [
        {"id": "1", "description": "Venmo Cashout 0001"},  # → venmo cashout — matches
        {"id": "2", "description": "Chase Bill Pay"},      # different — kept
        {"id": "3", "description": "VENMO 9988"},          # → venmo — different key — kept
    ]
    with patch("app.policy.transfers.policy_store.list_for_user",
               return_value=[_override(key="external:venmo cashout")]):
        out = pt.filter_external_candidates(
            MagicMock(), user_id=uuid4(), candidates=candidates,
        )

    assert [c["id"] for c in out] == ["2", "3"]


def test_filter_returns_unchanged_when_no_policies():
    candidates = [{"id": "1", "description": "Venmo"}]
    with patch("app.policy.transfers.policy_store.list_for_user", return_value=[]):
        out = pt.filter_external_candidates(
            MagicMock(), user_id=uuid4(), candidates=candidates,
        )
    assert out == candidates


def test_filter_returns_unchanged_on_lookup_failure():
    """Engine degrades gracefully — a broken policy table read should not
    nuke the user's pairing pool."""
    candidates = [{"id": "1", "description": "Venmo"}]
    with patch("app.policy.transfers.policy_store.list_for_user",
               side_effect=RuntimeError("DB down")):
        out = pt.filter_external_candidates(
            MagicMock(), user_id=uuid4(), candidates=candidates,
        )
    assert out == candidates


def test_filter_ignores_policies_without_always_external_flag():
    """Only policies with value.always_external=True are honored. Any other
    transfers-domain policy shape (future expansion) is ignored by this filter."""
    candidates = [{"id": "1", "description": "Venmo"}]
    irrelevant_policy = _override(
        key="dismiss_pair:acct_a:acct_b",
        value={"some_other_flag": True},  # NOT always_external
    )
    with patch("app.policy.transfers.policy_store.list_for_user",
               return_value=[irrelevant_policy]):
        out = pt.filter_external_candidates(
            MagicMock(), user_id=uuid4(), candidates=candidates,
        )
    assert out == candidates


def test_filter_handles_empty_candidates():
    with patch("app.policy.transfers.policy_store.list_for_user", return_value=[]):
        out = pt.filter_external_candidates(
            MagicMock(), user_id=uuid4(), candidates=[],
        )
    assert out == []
