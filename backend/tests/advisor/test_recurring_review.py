from uuid import uuid4

from app.advisor.parser import parse_recurring_review_reply
from app.engine.recurring.schema import (
    Direction, Frequency, RecurringRule, Source, Status,
)


def _pending_rule():
    return RecurringRule(
        id=uuid4(), user_id=uuid4(),
        keyword="Greystar Rent", normalized_key_pattern="greystar apts",
        amount_min=2750, amount_max=2850, amount_median=2800,
        frequency=Frequency.MONTHLY, direction=Direction.EXPENSE,
        confidence=0.55, status=Status.PENDING_REVIEW, source=Source.HEURISTIC,
    )


def test_parse_yes_returns_confirm_action():
    action = parse_recurring_review_reply("yes", _pending_rule())
    assert action.kind == "confirm"


def test_parse_no_returns_reject_action():
    action = parse_recurring_review_reply("no, that's a one-off", _pending_rule())
    assert action.kind == "reject"


def test_parse_edit_with_amount():
    action = parse_recurring_review_reply("edit amount to 2900", _pending_rule())
    assert action.kind == "edit"
    assert action.updates.get("amount_median") == 2900.0


def test_parse_freeform_add_recurring():
    action = parse_recurring_review_reply(
        "Add my Netflix subscription — $15.99 monthly.", None,
    )
    assert action.kind == "create"
    assert action.updates["keyword"].lower().startswith("netflix")
    assert action.updates["amount_median"] == 15.99
    assert action.updates["frequency"] == "monthly"


def test_parse_edit_like_input_with_no_rule_returns_noop():
    action = parse_recurring_review_reply("change amount to 50", None)
    assert action.kind == "noop"
    assert action.rule_id is None
    assert action.updates == {}


def test_parse_no_prefix_matches_broad_negations():
    # Current behavior: startswith("no") catches "not sure" and "none".
    # Document this so intent changes are caught.
    rule = _pending_rule()
    for text in ("no", "not sure", "none of these"):
        action = parse_recurring_review_reply(text, rule)
        assert action.kind == "reject", f"expected reject for {text!r}"
