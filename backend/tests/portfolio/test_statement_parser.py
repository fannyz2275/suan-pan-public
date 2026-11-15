from datetime import date
from unittest.mock import MagicMock, patch
import json
import pytest


@pytest.mark.parametrize('included,expected', [(24902.21, 0), (0, 24902.21), (10000, 14902.21)])
def test_cash_overlap_is_subtracted_once_without_changing_holdings(included, expected):
    from app.portfolio.statement_parser import parse_investment_statement
    payload = {'statement_date': '2026-10-01', 'cash_value': 24902.21,
               'cash_in_holdings': included, 'total_value_reported': 206725.26,
               'holdings': [
                   {'ticker': 'CASH', 'is_cash': True, 'quantity': 24902.21, 'price': 1, 'market_value': 24902.21},
                   {'ticker': 'VTI', 'quantity': 1, 'price': 181823.05, 'market_value': 181823.05}],
               'investment_transactions': [{'date': '2026-10-01', 'type': 'buy', 'amount': -10000}]}
    client = MagicMock()
    client.models.generate_content.return_value.text = json.dumps(payload)
    with patch('app.portfolio.statement_parser.gemini_client', return_value=client):
        result = parse_investment_statement('synthetic statement')
    assert result['cash_value'] == pytest.approx(expected)
    assert sum(h['market_value'] for h in result['holdings']) == pytest.approx(206725.26)
    assert result['investment_transactions'][0]['amount'] == -10000


def test_does_not_remove_cash_just_to_match_reported_total():
    from app.portfolio.statement_parser import parse_investment_statement
    client = MagicMock()
    client.models.generate_content.return_value.text = json.dumps({
        'cash_value': 100, 'total_value_reported': 500,
        'holdings': [{'ticker': 'VTI', 'quantity': 1, 'price': 500, 'market_value': 500}],
    })
    with patch('app.portfolio.statement_parser.gemini_client', return_value=client):
        assert parse_investment_statement('synthetic')['cash_value'] == 100


def test_parse_investment_statement_basic():
    from app.portfolio.statement_parser import parse_investment_statement

    fake_response = """
    {
      "statement_date": "2026-04-30",
      "cash_value": 1234.56,
      "account_hint": "Fidelity Brokerage ...1234",
      "total_value_reported": 19934.56,
      "holdings": [
        {"ticker": "NVDA", "name": "NVIDIA", "quantity": 10, "price": 950.0, "market_value": 9500.0, "cost_basis": 7000.0},
        {"ticker": "VOO", "name": "Vanguard S&P 500", "quantity": 20, "price": 460.0, "market_value": 9200.0, "cost_basis": null}
      ],
      "investment_transactions": [
        {"date": "2026-04-15", "type": "buy", "ticker": "NVDA", "quantity": 2, "price": 920.0, "amount": -1840.0},
        {"date": "2026-04-25", "type": "dividend", "ticker": "VOO", "quantity": null, "price": null, "amount": 18.50}
      ]
    }
    """
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = fake_response

    with patch("app.portfolio.statement_parser.gemini_client", return_value=fake_client):
        out = parse_investment_statement("ignored raw text")

    assert out["statement_date"] == "2026-04-30"
    assert out["cash_value"] == 1234.56
    assert out["account_hint"] == "Fidelity Brokerage ...1234"
    assert out["total_value_reported"] == 19934.56
    assert len(out["holdings"]) == 2
    nvda = next(h for h in out["holdings"] if h["ticker"] == "NVDA")
    assert nvda["quantity"] == 10
    assert nvda["cost_basis"] == 7000.0
    voo = next(h for h in out["holdings"] if h["ticker"] == "VOO")
    assert voo["cost_basis"] is None
    assert len(out["investment_transactions"]) == 2
    div = next(t for t in out["investment_transactions"] if t["type"] == "dividend")
    assert div["amount"] == 18.50
    assert div["quantity"] is None


def test_parse_investment_statement_strips_markdown_fences():
    from app.portfolio.statement_parser import parse_investment_statement

    fake_response = """```json
    {"statement_date": "2026-03-31", "cash_value": 0, "holdings": [], "investment_transactions": []}
    ```"""
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = fake_response

    with patch("app.portfolio.statement_parser.gemini_client", return_value=fake_client):
        out = parse_investment_statement("ignored")

    assert out["statement_date"] == "2026-03-31"
    assert out["holdings"] == []
    assert out["investment_transactions"] == []


def test_parse_investment_statement_invalid_response_returns_empty_skeleton():
    from app.portfolio.statement_parser import parse_investment_statement

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = "not json at all"

    with patch("app.portfolio.statement_parser.gemini_client", return_value=fake_client):
        out = parse_investment_statement("ignored")

    # Degrades gracefully — caller can show "couldn't parse, please paste again."
    assert out["holdings"] == []
    assert out["investment_transactions"] == []


def test_parse_investment_statement_extracts_total_value_reported():
    from app.portfolio.statement_parser import parse_investment_statement

    fake_response = """
    {
      "statement_date": "2026-04-30",
      "cash_value": 100,
      "total_value_reported": 19999.99,
      "holdings": [],
      "investment_transactions": []
    }
    """
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = fake_response

    with patch("app.portfolio.statement_parser.gemini_client", return_value=fake_client):
        out = parse_investment_statement("ignored")

    assert out["total_value_reported"] == 19999.99


def test_parse_investment_statement_total_value_reported_null_when_absent():
    from app.portfolio.statement_parser import parse_investment_statement

    fake_response = """
    {
      "statement_date": "2026-04-30",
      "cash_value": 0,
      "holdings": [],
      "investment_transactions": []
    }
    """
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = fake_response

    with patch("app.portfolio.statement_parser.gemini_client", return_value=fake_client):
        out = parse_investment_statement("ignored")

    assert out["total_value_reported"] is None


def test_parse_investment_statement_clamps_invalid_txn_type():
    from app.portfolio.statement_parser import parse_investment_statement

    fake_response = """
    {
      "statement_date": "2026-04-30",
      "cash_value": 0,
      "holdings": [],
      "investment_transactions": [
        {"date": "2026-04-15", "type": "purchase", "ticker": "NVDA", "amount": -100}
      ]
    }
    """
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value.text = fake_response

    with patch("app.portfolio.statement_parser.gemini_client", return_value=fake_client):
        out = parse_investment_statement("ignored")

    # "purchase" isn't valid; fall back to "buy" since amount<0
    assert out["investment_transactions"][0]["type"] == "buy"
