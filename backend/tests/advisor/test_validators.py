from app.advisor.validators import (
    check_number_consistency,
    redact_internal_terms,
    redact_pii,
    strip_markdown_tables,
    validate_actions,
)


def test_strip_markdown_tables_removes_pipe_table():
    text = (
        "Here are the rules:\n\n"
        "| Merchant | Frequency | Amount |\n"
        "|----------|-----------|--------|\n"
        "| Verizon  | monthly   | $108 |\n"
        "| Comcast  | monthly   | $70  |\n\n"
        "Let me know if you want to cancel any."
    )
    cleaned, n = strip_markdown_tables(text)
    assert n == 1
    assert "|" not in cleaned
    assert cleaned.startswith("Here are the rules:")
    assert cleaned.endswith("cancel any.")


def test_strip_markdown_tables_leaves_non_table_pipes_alone():
    text = "Use the `a | b` operator to filter results."
    cleaned, n = strip_markdown_tables(text)
    assert n == 0
    assert cleaned == text.strip()


def test_strip_markdown_tables_handles_multiple_tables():
    text = (
        "First:\n\n"
        "| A | B |\n| - | - |\n| 1 | 2 |\n\n"
        "Second:\n\n"
        "| X | Y |\n| - | - |\n| 9 | 8 |\n"
    )
    _, n = strip_markdown_tables(text)
    assert n == 2


def test_numbers_match_within_tolerance():
    tool_outputs = [{"total": 2100.00}]
    warnings = check_number_consistency("You spent $2,140 on food.", tool_outputs)
    assert warnings == []


def test_numbers_mismatch_flagged():
    tool_outputs = [{"total": 2100.00}]
    warnings = check_number_consistency("You spent $1,500 on food.", tool_outputs)
    assert len(warnings) == 1
    assert warnings[0]["type"] == "number_mismatch"
    assert warnings[0]["claimed"] == 1500.0
    assert warnings[0]["closest_tool_result"] == 2100.0


def test_ignores_contextual_numbers():
    warnings = check_number_consistency("You are 32 years old. Savings: $100.", [{"total": 100}])
    assert warnings == []  # '32' is not a $-prefixed amount


def test_redacts_ssn():
    text, warnings = redact_pii("My SSN is 123-45-6789.")
    assert "[REDACTED]" in text
    assert "123-45-6789" not in text
    assert any(w["pattern"] == "ssn" for w in warnings)


def test_redacts_credit_card():
    text, warnings = redact_pii("Card: 4111 1111 1111 1111")
    assert "[REDACTED]" in text
    assert any(w["pattern"] == "credit_card" for w in warnings)


def test_redacts_plaid_access_token():
    text, warnings = redact_pii("token: access-sandbox-abc12345")
    assert "[REDACTED]" in text
    assert any(w["pattern"] == "plaid_access_token" for w in warnings)


def test_clean_text_unchanged():
    text, warnings = redact_pii("Food $2100")
    assert text == "Food $2100"
    assert warnings == []


def test_valid_goal_passes():
    raw = {
        "new_goals": [
            {"name": "House", "type": "house", "target_amount": 100000, "target_date": "2030-01-01"}
        ],
    }
    valid, warnings = validate_actions(raw)
    assert len(valid["new_goals"]) == 1
    assert warnings == []


def test_invalid_goal_dropped():
    raw = {"new_goals": [{"name": "X"}]}  # missing fields
    valid, warnings = validate_actions(raw)
    assert valid["new_goals"] == []
    assert len(warnings) == 1
    assert warnings[0]["type"] == "invalid_action"


def test_extra_keys_ignored():
    """Stale advisor responses that still emit `new_action_items` are dropped
    silently — the validator only consumes `new_goals` now."""
    raw = {
        "new_goals": [],
        "new_action_items": [{"description": "Open Roth IRA"}],
    }
    valid, warnings = validate_actions(raw)
    assert valid == {"new_goals": []}
    assert warnings == []


def test_redact_bare_snake_case_tool_name():
    """Bare tool name with no preceding article gets the noun-phrase replacement."""
    text, warnings = redact_internal_terms("Use simulate_decision to project outcomes.")
    assert text == "Use the simulator to project outcomes."
    assert any(w["pattern"] == "tool_simulate_decision" for w in warnings)


def test_redact_absorbs_preceding_definite_article():
    """`the score_goal` should not produce `the the feasibility scorer`."""
    text, _ = redact_internal_terms("The score_goal tool gives the score.")
    assert text == "The feasibility scorer tool gives the score."
    text2, _ = redact_internal_terms("I called the score_goal tool.")
    assert text2 == "I called the feasibility scorer tool."


def test_redact_absorbs_preceding_indefinite_article():
    """`a simulate_decision` should not produce `a the simulator`."""
    text, _ = redact_internal_terms("I have a simulate_decision tool available.")
    assert text == "I have the simulator tool available."
    text2, _ = redact_internal_terms("an monte_carlo run")
    assert text2 == "the Monte Carlo simulator run"
