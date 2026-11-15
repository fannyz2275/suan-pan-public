from unittest.mock import MagicMock
from uuid import UUID, uuid4

from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)
from app.engine.recurring.store import load_rules, upsert_rules, serialize_rule, deserialize_rule


def _rule(**overrides):
    base = dict(
        id=uuid4(),
        user_id=uuid4(),
        keyword="Rent",
        normalized_key_pattern="greystar apts",
        amount_min=2750, amount_max=2850, amount_median=2800,
        frequency=Frequency.MONTHLY, direction=Direction.EXPENSE,
        confidence=0.9, status=Status.AUTO_APPLIED, source=Source.HEURISTIC,
    )
    base.update(overrides)
    return RecurringRule(**base)


def test_serialize_roundtrip():
    r = _rule()
    row = serialize_rule(r)
    assert row["frequency"] == "monthly"
    assert row["direction"] == "expense"
    back = deserialize_rule(row)
    assert back.keyword == r.keyword
    assert back.frequency == Frequency.MONTHLY


def test_load_rules_returns_parsed_models():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        serialize_rule(_rule())
    ]
    user_id = uuid4()
    rules = load_rules(client, user_id)
    assert len(rules) == 1
    assert isinstance(rules[0], RecurringRule)


def test_upsert_rules_routes_by_id():
    client = MagicMock()
    existing = _rule()
    new = _rule(id=None, status=Status.PROPOSED)
    upsert_rules(client, [existing, new])
    # Expect one update for existing, one insert for new (id None).
    upsert_calls = client.table.return_value.upsert.call_args_list
    assert len(upsert_calls) == 1  # single upsert batches both rows


def test_mixed_batch_has_uniform_keys_and_returns_persisted_ids():
    client = MagicMock()
    existing = _rule()
    new = _rule(id=None)
    upsert_rules(client, [existing, new])
    rows = client.table.return_value.upsert.call_args.args[0]
    assert set(rows[0]) == set(rows[1])
    assert UUID(rows[1]['id']) == new.id
    assert rows[0]['id'] == str(existing.id)
