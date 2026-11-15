"""Spec B Phase 2/3 — engine module test for app.portfolio.statement_parser.

Gemini is mocked (Spec B §2 — no LLM in this layer). The mock returns a fixed
JSON response; we lock the parsed dict via a golden snapshot.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.portfolio.statement_parser import parse_investment_statement


def _fake_gemini(text: str) -> MagicMock:
    client = MagicMock()
    client.models.generate_content.return_value.text = text
    return client


_GEMINI_RESPONSE_FIDELITY = """
{
  "statement_date": "2026-04-30",
  "cash_value": 1234.56,
  "account_hint": "Fidelity Brokerage ...1234",
  "total_value_reported": 19934.56,
  "holdings": [
    {"ticker": "NVDA", "name": "NVIDIA",
     "quantity": 10, "price": 950.0, "market_value": 9500.0, "cost_basis": 7000.0},
    {"ticker": "VOO", "name": "Vanguard S&P 500",
     "quantity": 20, "price": 460.0, "market_value": 9200.0, "cost_basis": null}
  ],
  "investment_transactions": [
    {"date": "2026-04-15", "type": "buy", "ticker": "NVDA",
     "quantity": 2, "price": 920.0, "amount": -1840.0},
    {"date": "2026-04-25", "type": "dividend", "ticker": "VOO",
     "quantity": null, "price": null, "amount": 18.50}
  ]
}
"""


def test_parse_statement_fidelity_golden(snapshot_json):
    with patch(
        "app.portfolio.statement_parser.gemini_client",
        return_value=_fake_gemini(_GEMINI_RESPONSE_FIDELITY),
    ):
        parsed = parse_investment_statement("ignored raw text")
    assert parsed == snapshot_json


def test_parse_statement_strips_markdown_fences():
    response = """```json
    {"statement_date": "2026-03-31", "cash_value": 0,
     "holdings": [], "investment_transactions": []}
    ```"""
    with patch(
        "app.portfolio.statement_parser.gemini_client",
        return_value=_fake_gemini(response),
    ):
        parsed = parse_investment_statement("ignored")
    assert parsed["statement_date"] == "2026-03-31"


def test_parse_statement_empty_response_returns_empty_skeleton():
    with patch(
        "app.portfolio.statement_parser.gemini_client",
        return_value=_fake_gemini(""),
    ):
        parsed = parse_investment_statement("ignored")
    assert parsed["holdings"] == []
    assert parsed["investment_transactions"] == []
    assert parsed["cash_value"] == 0


def test_parse_statement_required_keys_present():
    """All keys promised by the schema must be in the parsed dict, even when
    Gemini omits them."""
    response = '{"statement_date": null}'
    with patch(
        "app.portfolio.statement_parser.gemini_client",
        return_value=_fake_gemini(response),
    ):
        parsed = parse_investment_statement("ignored")
    for key in ("statement_date", "cash_value", "holdings",
                "investment_transactions", "account_hint",
                "total_value_reported"):
        assert key in parsed, f"missing key: {key}"
