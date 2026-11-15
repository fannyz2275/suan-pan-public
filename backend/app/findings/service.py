from datetime import datetime, timezone
from typing import Any, Iterable, List

from app.findings.schema import Finding

_MAX_FINDINGS = 25


def _parse_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def build_finding_from_rule(rule: dict) -> Finding:
    keyword = (rule.get("keyword") or "").strip() or "Recurring charge"
    amount = float(rule.get("amount_median") or 0)
    freq = rule.get("frequency") or "monthly"
    title = f"{keyword.title()} ${amount:,.2f}/{freq[:3]}"
    body = (
        f"Detected {rule.get('occurrences_observed', 0)} occurrences. "
        f"Direction: {rule.get('direction', 'expense')}."
    )
    return Finding(
        id=str(rule["id"]),
        kind="recurring",
        title=title,
        body=body,
        evidence={
            "amount_median": amount,
            "frequency": freq,
            "direction": rule.get("direction"),
            "occurrences_observed": rule.get("occurrences_observed"),
            "keyword": keyword,
        },
        created_at=_parse_dt(rule.get("created_at")),
    )


def build_finding_from_transfer(txn: dict) -> Finding:
    amount = float(txn.get("amount") or 0)
    desc = (txn.get("description") or "Transfer").strip()
    title = f"Possible transfer: {desc} (${abs(amount):,.0f})"
    body = (
        f"Marked as needs-review on {txn.get('date')}. "
        f"Confirm if this is a transfer between your own accounts."
    )
    return Finding(
        id=str(txn["id"]),
        kind="transfer",
        title=title,
        body=body,
        evidence={
            "amount": amount,
            "description": desc,
            "date": txn.get("date"),
            "transfer_group_id": txn.get("transfer_group_id"),
        },
        created_at=_parse_dt(txn.get("created_at")),
    )


def list_pending_findings(
    rules: Iterable[dict],
    transfer_txns: Iterable[dict],
) -> List[Finding]:
    out: list[Finding] = []
    for r in rules:
        out.append(build_finding_from_rule(r))
    for t in transfer_txns:
        out.append(build_finding_from_transfer(t))
    out.sort(key=lambda f: f.created_at)
    return out[:_MAX_FINDINGS]
