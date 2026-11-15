import pytest
from pydantic import ValidationError

from app.engine.recurring.schema import RecurringRule, Frequency, Direction, Status, Source


def _valid_payload(**overrides):
    base = dict(
        user_id="11111111-1111-1111-1111-111111111111",
        keyword="Greystar Rent",
        normalized_key_pattern="greystar apts",
        amount_min=2750.00,
        amount_max=2850.00,
        amount_median=2800.00,
        frequency=Frequency.MONTHLY,
        direction=Direction.EXPENSE,
        confidence=0.92,
        status=Status.AUTO_APPLIED,
        source=Source.HEURISTIC,
        last_seen_date="2026-04-01",
        next_expected_date="2026-05-01",
        occurrences_observed=12,
        sample_transaction_ids=[],
    )
    base.update(overrides)
    return base


def test_valid_rule_parses():
    rule = RecurringRule(**_valid_payload())
    assert rule.frequency == Frequency.MONTHLY
    assert rule.confidence == 0.92


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        RecurringRule(**_valid_payload(confidence=1.5))
    with pytest.raises(ValidationError):
        RecurringRule(**_valid_payload(confidence=-0.1))


def test_amount_min_gt_max_rejected():
    with pytest.raises(ValidationError):
        RecurringRule(**_valid_payload(amount_min=100, amount_max=50, amount_median=75))


def test_unknown_frequency_rejected():
    with pytest.raises(ValidationError):
        RecurringRule(**_valid_payload(frequency="daily"))
