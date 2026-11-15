from datetime import datetime, timezone

from app.advisor.findings_prompt import render_findings_prompt
from app.findings.schema import Finding


def test_render_findings_prompt_lists_each():
    findings = [
        Finding(
            id="r1",
            kind="recurring",
            title="Netflix $15.99/mo",
            body="...",
            evidence={},
            created_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        Finding(
            id="t1",
            kind="transfer",
            title="Possible transfer: $500",
            body="...",
            evidence={},
            created_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
    ]
    prompt = render_findings_prompt(findings)
    assert "id=r1 kind=recurring" in prompt
    assert "id=t1 kind=transfer" in prompt
    assert "review of 2 backend-detected findings" in prompt
