from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.findings.schema import Decision, Finding


def test_finding_validates_kind():
    f = Finding(
        id="r1",
        kind="recurring",
        title="Netflix $15.99/mo",
        body="Charged on the 5th of every month for 6 months.",
        evidence={"frequency": "monthly", "amount_median": 15.99},
        created_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )
    assert f.kind == "recurring"


def test_finding_rejects_invalid_kind():
    with pytest.raises(ValidationError):
        Finding(
            id="x",
            kind="other",
            title="t",
            body="b",
            evidence={},
            created_at=datetime.now(timezone.utc),
        )


def test_decision_accepts_known_values():
    Decision(decision="accept")
    Decision(decision="reject")


def test_decision_rejects_unknown():
    with pytest.raises(ValidationError):
        Decision(decision="maybe")
