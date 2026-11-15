"""Assertions that SYSTEM_PROMPT in app.advisor.context contains required sections."""
from __future__ import annotations


def test_system_prompt_contains_portfolio_attribution_narration_section():
    from app.advisor.context import SYSTEM_PROMPT
    assert "PORTFOLIO ATTRIBUTION NARRATION" in SYSTEM_PROMPT
    assert "portfolio_get_attribution" in SYSTEM_PROMPT
    assert "unattributed" in SYSTEM_PROMPT
    assert "portfolio_get_holdings" in SYSTEM_PROMPT
    assert "portfolio_get_exposure" in SYSTEM_PROMPT
