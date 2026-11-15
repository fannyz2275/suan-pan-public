from app.advisor.context import SYSTEM_PROMPT


def test_advisor_uses_everyday_language_without_equating_cash_and_income():
    assert "Cash you can use" in SYSTEM_PROMPT
    assert "What you owe" in SYSTEM_PROMPT
    assert "Income coverage" in SYSTEM_PROMPT
    assert "not proof" in SYSTEM_PROMPT
