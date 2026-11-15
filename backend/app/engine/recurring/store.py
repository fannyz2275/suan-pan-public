from __future__ import annotations

from typing import Any, List
from uuid import UUID, uuid4

from supabase import Client

from app.engine.recurring.schema import RecurringRule

_RULES_TABLE = "recurring_rules"
_MATCHES_TABLE = "recurring_rule_matches"


def serialize_rule(rule: RecurringRule) -> dict[str, Any]:
    data = rule.model_dump(mode="json")
    # Drop None ids so Postgres generates them.
    if data.get("id") is None:
        data.pop("id", None)
    data.pop("created_at", None)
    data.pop("updated_at", None)
    return data


def deserialize_rule(row: dict[str, Any]) -> RecurringRule:
    return RecurringRule(**row)


def load_rules(client: Client, user_id: UUID) -> List[RecurringRule]:
    resp = client.table(_RULES_TABLE).select("*").eq("user_id", str(user_id)).execute()
    return [deserialize_rule(r) for r in (resp.data or [])]


def upsert_rules(client: Client, rules: List[RecurringRule]) -> None:
    if not rules:
        return
    # PostgREST bulk writes require identical keys for new and existing rows.
    # Keep generated IDs on the models so the scan response can edit new rules.
    for rule in rules:
        if rule.id is None:
            rule.id = uuid4()
    rows = [serialize_rule(r) for r in rules]
    client.table(_RULES_TABLE).upsert(rows, on_conflict="id").execute()


def write_matches(client: Client, bindings: list[tuple[UUID, str]]) -> None:
    """Upsert (rule_id, transaction_id) pairs. Idempotent via PK (rule_id, transaction_id)."""
    if not bindings:
        return
    rows = [{"rule_id": str(rid), "transaction_id": txn} for rid, txn in bindings]
    client.table(_MATCHES_TABLE).upsert(rows, on_conflict="rule_id,transaction_id").execute()
