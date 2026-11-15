import pytest

from app.engine.category_baseline.schema import Tier
from app.engine.category_baseline.tier import classify_tier


@pytest.mark.parametrize("months,expected", [
    (0, Tier.T1),
    (2, Tier.T1),
    (3, Tier.T2),
    (4, Tier.T2),
    (5, Tier.T3),
    (11, Tier.T3),
    (12, Tier.T4),
    (13, Tier.T4),
    (24, Tier.T4),
])
def test_classify_tier_boundaries(months, expected):
    assert classify_tier(months) is expected


def test_opted_out_forces_t1():
    assert classify_tier(15, opted_out=True) is Tier.T1
