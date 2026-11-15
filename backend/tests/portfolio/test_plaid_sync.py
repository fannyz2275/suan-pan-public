from datetime import date


def test_map_plaid_holdings_groups_by_account_and_attaches_security():
    from app.portfolio.plaid_sync import map_plaid_holdings

    securities = [
        {"security_id": "sec-nvda", "ticker_symbol": "NVDA", "name": "NVIDIA",
         "type": "equity", "is_cash_equivalent": False},
        {"security_id": "sec-voo", "ticker_symbol": "VOO", "name": "Vanguard S&P 500 ETF",
         "type": "etf", "is_cash_equivalent": False},
        {"security_id": "sec-cash", "ticker_symbol": None, "name": "Cash",
         "type": "cash", "is_cash_equivalent": True},
    ]
    holdings = [
        {"account_id": "p-acc-1", "security_id": "sec-nvda",
         "quantity": 10, "institution_price": 950.0,
         "institution_value": 9500.0, "cost_basis": 7000.0},
        {"account_id": "p-acc-1", "security_id": "sec-voo",
         "quantity": 20, "institution_price": 460.0,
         "institution_value": 9200.0, "cost_basis": None},
        {"account_id": "p-acc-1", "security_id": "sec-cash",
         "quantity": 1, "institution_price": 1.0,
         "institution_value": 350.0, "cost_basis": None},
        {"account_id": "p-acc-2", "security_id": "sec-nvda",
         "quantity": 5, "institution_price": 950.0,
         "institution_value": 4750.0, "cost_basis": 3500.0},
    ]
    by_account = map_plaid_holdings(holdings, securities)
    assert set(by_account.keys()) == {"p-acc-1", "p-acc-2"}

    acc1 = by_account["p-acc-1"]
    # Cash holdings are stripped from holdings list and aggregated to cash_value.
    assert acc1["cash_value"] == 350.0
    tickers = {h["ticker"] for h in acc1["holdings"]}
    assert tickers == {"NVDA", "VOO"}
    nvda = next(h for h in acc1["holdings"] if h["ticker"] == "NVDA")
    assert nvda["quantity"] == 10
    assert nvda["price"] == 950.0
    assert nvda["market_value"] == 9500.0
    assert nvda["cost_basis"] == 7000.0
    assert nvda["name"] == "NVIDIA"

    acc2 = by_account["p-acc-2"]
    assert acc2["cash_value"] == 0
    assert len(acc2["holdings"]) == 1


def test_map_plaid_holdings_skips_holdings_with_unknown_security():
    from app.portfolio.plaid_sync import map_plaid_holdings

    holdings = [{"account_id": "p-acc-1", "security_id": "sec-missing",
                 "quantity": 1, "institution_price": 100, "institution_value": 100}]
    by_account = map_plaid_holdings(holdings, securities=[])
    # No security info → drop the holding rather than emit a row with empty ticker.
    assert by_account == {} or by_account["p-acc-1"]["holdings"] == []


def test_map_plaid_investment_transactions_normalizes_types_and_signs():
    from app.portfolio.plaid_sync import map_plaid_investment_transactions

    securities = [
        {"security_id": "sec-nvda", "ticker_symbol": "NVDA",
         "type": "equity", "name": "NVIDIA"},
    ]
    plaid_txns = [
        # Plaid "buy": amount is positive cash-out, we flip to negative.
        {"investment_transaction_id": "p-1", "account_id": "p-acc-1",
         "security_id": "sec-nvda", "date": "2026-04-15",
         "type": "buy", "subtype": None,
         "quantity": 2, "price": 920, "fees": 0, "amount": 1840},
        # Plaid "sell": positive cash-in, keep positive.
        {"investment_transaction_id": "p-2", "account_id": "p-acc-1",
         "security_id": "sec-nvda", "date": "2026-04-20",
         "type": "sell", "subtype": None,
         "quantity": -1, "price": 1000, "fees": 0, "amount": 1000},
        # Plaid "cash"/"dividend": small positive cash-in.
        {"investment_transaction_id": "p-3", "account_id": "p-acc-1",
         "security_id": "sec-nvda", "date": "2026-04-25",
         "type": "cash", "subtype": "dividend",
         "quantity": 0, "price": 0, "fees": 0, "amount": 18.50},
        # Plaid "fee": negative cash-out, keep negative.
        {"investment_transaction_id": "p-4", "account_id": "p-acc-1",
         "security_id": None, "date": "2026-04-30",
         "type": "fee", "subtype": "account_fee",
         "quantity": 0, "price": 0, "fees": 5, "amount": -5},
        # Plaid "transfer" subtype "deposit"
        {"investment_transaction_id": "p-5", "account_id": "p-acc-1",
         "security_id": None, "date": "2026-04-01",
         "type": "transfer", "subtype": "deposit",
         "quantity": 0, "price": 0, "fees": 0, "amount": 5000},
    ]
    by_account = map_plaid_investment_transactions(plaid_txns, securities)
    # Golden locks the full normalised output — sign convention regressions
    # (Spec B I8) become a single visible diff rather than five scattered
    # assertion failures.
    canonical = {
        acct: sorted(rows, key=lambda r: r["plaid_investment_transaction_id"])
        for acct, rows in by_account.items()
    }
    assert canonical == _GOLDEN_PLAID_TXNS_NORMALIZED


_GOLDEN_PLAID_TXNS_NORMALIZED = {
    "p-acc-1": [
        {"plaid_investment_transaction_id": "p-1", "date": "2026-04-15",
         "type": "buy", "ticker": "NVDA", "quantity": 2.0, "price": 920.0,
         "amount": -1840.0},
        {"plaid_investment_transaction_id": "p-2", "date": "2026-04-20",
         "type": "sell", "ticker": "NVDA", "quantity": -1.0, "price": 1000.0,
         "amount": 1000.0},
        {"plaid_investment_transaction_id": "p-3", "date": "2026-04-25",
         "type": "dividend", "ticker": "NVDA", "quantity": None, "price": None,
         "amount": 18.5},
        {"plaid_investment_transaction_id": "p-4", "date": "2026-04-30",
         "type": "fee", "ticker": None, "quantity": None, "price": None,
         "amount": -5.0},
        {"plaid_investment_transaction_id": "p-5", "date": "2026-04-01",
         "type": "transfer_in", "ticker": None, "quantity": None, "price": None,
         "amount": 5000.0},
    ],
}


def test_map_plaid_investment_transactions_drops_unknown_type():
    from app.portfolio.plaid_sync import map_plaid_investment_transactions

    plaid_txns = [{
        "investment_transaction_id": "p-x", "account_id": "p-acc-1",
        "security_id": None, "date": "2026-04-15",
        "type": "cancel", "subtype": "buy",
        "quantity": 0, "price": 0, "fees": 0, "amount": 0,
    }]
    by_account = map_plaid_investment_transactions(plaid_txns, securities=[])
    # "cancel" doesn't map cleanly; drop the row.
    assert by_account == {} or by_account["p-acc-1"] == []


def test_extract_plaid_securities_for_reference():
    from app.portfolio.plaid_sync import securities_to_reference_rows

    securities = [
        {"security_id": "sec-nvda", "ticker_symbol": "NVDA", "name": "NVIDIA",
         "type": "equity", "is_cash_equivalent": False},
        {"security_id": "sec-voo", "ticker_symbol": "VOO", "name": "Vanguard 500",
         "type": "etf", "is_cash_equivalent": False},
        {"security_id": "sec-cash", "ticker_symbol": None, "name": "Cash",
         "type": "cash", "is_cash_equivalent": True},
        {"security_id": "sec-bnd", "ticker_symbol": "BND", "name": "Vanguard Bond",
         "type": "fixed income", "is_cash_equivalent": False},
    ]
    rows = securities_to_reference_rows(securities)
    by_ticker = {r["ticker"]: r for r in rows}
    # Cash equivalents and missing tickers are skipped — they're not securities.
    assert "NVDA" in by_ticker and "VOO" in by_ticker and "BND" in by_ticker
    assert by_ticker["NVDA"]["security_type"] == "stock"
    assert by_ticker["NVDA"]["asset_class"] == "equity"
    assert by_ticker["VOO"]["security_type"] == "etf"
    assert by_ticker["VOO"]["asset_class"] == "equity"
    assert by_ticker["BND"]["asset_class"] == "fixed_income"
    assert by_ticker["BND"]["security_type"] == "bond"
    # Plaid doesn't provide sector/region/look_through reliably — leave null.
    assert by_ticker["NVDA"]["sector"] is None


# ---------------------------------------------------------------------------
# Task 3: sync_plaid_investments orchestrator tests
# ---------------------------------------------------------------------------

from datetime import date
from unittest.mock import MagicMock, patch


def _fake_plaid_client_with_responses(holdings_response, txns_response):
    client = MagicMock()
    client.investments_holdings_get.return_value = holdings_response
    client.investments_transactions_get.return_value = txns_response
    return client


def test_sync_plaid_investments_writes_snapshot_per_account():
    from app.portfolio.plaid_sync import sync_plaid_investments

    db = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "plaid_items":
            t.select.return_value.eq.return_value.execute.return_value.data = [
                {"access_token": "tok-1", "item_id": "item-1"},
            ]
        elif name == "accounts":
            # Two investment accounts that match Plaid account_ids
            t.select.return_value.eq.return_value.in_.return_value.eq.return_value.execute.return_value.data = [
                {"id": "our-acc-1", "plaid_account_id": "p-acc-1", "type": "brokerage"},
                {"id": "our-acc-2", "plaid_account_id": "p-acc-2", "type": "retirement"},
            ]
        elif name == "security_reference":
            # No existing securities — upsert is a no-op for the assertion.
            t.upsert.return_value.execute.return_value.data = []
        elif name == "portfolio_snapshots":
            t.insert.return_value.execute.return_value.data = [{
                "id": "new-snap", "user_id": "u", "account_id": "x",
                "snapshot_date": "2026-05-07", "source": "plaid",
                "total_value": 0, "cash_value": 0,
                "created_at": "2026-05-07T00:00:00Z",
            }]
            t.update.return_value.eq.return_value.eq.return_value.eq.return_value.neq.return_value.is_.return_value.execute.return_value.data = []
        elif name == "snapshot_holdings":
            t.insert.return_value.execute.return_value.data = []
        elif name == "investment_transactions":
            existing = MagicMock()
            existing.execute.return_value.data = []
            t.select.return_value.eq.return_value.in_.return_value = existing
            t.insert.return_value.execute.return_value.data = []
        return t
    db.table.side_effect = table

    holdings_response = {
        "accounts": [
            {"account_id": "p-acc-1", "balances": {"current": 10000.0}},
            {"account_id": "p-acc-2", "balances": {"current": 5000.0}},
        ],
        "holdings": [
            {"account_id": "p-acc-1", "security_id": "sec-nvda",
             "quantity": 10, "institution_price": 950,
             "institution_value": 9500, "cost_basis": 7000},
            {"account_id": "p-acc-1", "security_id": "sec-cash",
             "quantity": 1, "institution_price": 1.0,
             "institution_value": 500, "cost_basis": None},
            {"account_id": "p-acc-2", "security_id": "sec-voo",
             "quantity": 11, "institution_price": 460,
             "institution_value": 5060, "cost_basis": 4500},
        ],
        "securities": [
            {"security_id": "sec-nvda", "ticker_symbol": "NVDA", "name": "NVIDIA",
             "type": "equity", "is_cash_equivalent": False},
            {"security_id": "sec-voo", "ticker_symbol": "VOO", "name": "Vanguard 500",
             "type": "etf", "is_cash_equivalent": False},
            {"security_id": "sec-cash", "ticker_symbol": None, "name": "Cash",
             "type": "cash", "is_cash_equivalent": True},
        ],
    }
    txns_response = {
        "investment_transactions": [
            {"investment_transaction_id": "p-tx-1", "account_id": "p-acc-1",
             "security_id": "sec-nvda", "date": date(2026, 5, 1),
             "type": "buy", "subtype": None,
             "quantity": 2, "price": 920, "fees": 0, "amount": 1840},
        ],
        "securities": [
            {"security_id": "sec-nvda", "ticker_symbol": "NVDA", "name": "NVIDIA",
             "type": "equity", "is_cash_equivalent": False},
        ],
    }

    plaid_client = _fake_plaid_client_with_responses(holdings_response, txns_response)
    snaps = sync_plaid_investments(db, user_id="u", plaid_client=plaid_client)

    # One snapshot per investment account.
    assert len(snaps) == 2
    # Plaid client called once per item × 2 endpoints.
    assert plaid_client.investments_holdings_get.call_count == 1
    assert plaid_client.investments_transactions_get.call_count == 1


def test_sync_plaid_investments_handles_product_not_ready_gracefully():
    from app.portfolio.plaid_sync import sync_plaid_investments

    import plaid
    err = plaid.ApiException(status=400, reason="bad request")
    err.body = '{"error_code": "PRODUCT_NOT_READY", "error_message": "..."}'

    db = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "plaid_items":
            t.select.return_value.eq.return_value.execute.return_value.data = [
                {"access_token": "tok-1", "item_id": "item-1"},
            ]
        return t
    db.table.side_effect = table

    plaid_client = MagicMock()
    plaid_client.investments_holdings_get.side_effect = err

    # Should NOT raise; should return empty list and let caller surface the failure.
    snaps = sync_plaid_investments(db, user_id="u", plaid_client=plaid_client)
    assert snaps == []
