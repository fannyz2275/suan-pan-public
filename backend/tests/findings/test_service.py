from datetime import datetime, timezone

from app.findings.service import (
    build_finding_from_rule,
    build_finding_from_transfer,
    list_pending_findings,
)


def test_recurring_rule_to_finding():
    rule = {
        "id": "r1",
        "keyword": "netflix",
        "amount_median": 15.99,
        "frequency": "monthly",
        "direction": "expense",
        "occurrences_observed": 6,
        "created_at": "2026-04-01T00:00:00Z",
    }
    f = build_finding_from_rule(rule)
    assert f.id == "r1"
    assert f.kind == "recurring"
    assert "Netflix" in f.title
    assert "15.99" in f.title
    assert f.evidence["frequency"] == "monthly"


def test_transfer_pair_to_finding():
    txn = {
        "id": "t1",
        "amount": -500.0,
        "description": "Transfer to Savings",
        "date": "2026-04-15",
        "transfer_group_id": "g1",
        "created_at": "2026-04-15T12:00:00Z",
    }
    f = build_finding_from_transfer(txn)
    assert f.id == "t1"
    assert f.kind == "transfer"
    assert "transfer" in f.title.lower()
    assert "$500" in f.title
    assert f.evidence["transfer_group_id"] == "g1"


def test_list_pending_findings_orders_by_created_at_and_caps():
    rules = [
        {
            "id": f"r{i}",
            "keyword": f"merchant{i}",
            "amount_median": 10.0,
            "frequency": "monthly",
            "direction": "expense",
            "occurrences_observed": 3,
            "created_at": f"2026-01-{i + 1:02d}T00:00:00Z",
        }
        for i in range(20)
    ]
    txns = [
        {
            "id": f"t{i}",
            "amount": -100.0,
            "description": f"transfer{i}",
            "date": "2026-04-01",
            "transfer_group_id": f"g{i}",
            "created_at": f"2026-02-{i + 1:02d}T00:00:00Z",
        }
        for i in range(10)
    ]
    findings = list_pending_findings(rules, txns)
    assert len(findings) == 25
    assert findings[0].created_at < findings[-1].created_at
    assert findings[0].id == "r0"


def test_list_pending_handles_missing_created_at():
    rules = [
        {
            "id": "rA",
            "keyword": "a",
            "amount_median": 1.0,
            "frequency": "monthly",
            "direction": "expense",
            "occurrences_observed": 1,
        }
    ]
    findings = list_pending_findings(rules, [])
    assert len(findings) == 1
    assert findings[0].created_at.tzinfo is not None
