from datetime import date


def _txn(date_str, type_, amount, ticker=None, qty=None, price=None, cost_basis_at_sell=None):
    return {
        "date": date_str, "type": type_, "amount": amount,
        "ticker": ticker, "quantity": qty, "price": price,
        "cost_basis_at_sell": cost_basis_at_sell,
    }


def test_attribution_pure_market_when_no_txns():
    from app.portfolio.attribution import compute_attribution
    out = compute_attribution(start_value=100_000, end_value=110_000, transactions=[])
    assert out["start_value"] == 100_000
    assert out["end_value"] == 110_000
    assert out["market"] == 10_000
    assert out["contributions"] == 0
    assert out["withdrawals"] == 0
    assert out["dividends"] == 0
    assert out["trades"] == 0
    assert out["unattributed"] == 0


def test_attribution_separates_contributions_from_market():
    from app.portfolio.attribution import compute_attribution
    txns = [_txn("2026-04-15", "transfer_in", 5_000)]
    out = compute_attribution(start_value=100_000, end_value=110_000, transactions=txns)
    assert out["contributions"] == 5_000
    assert out["market"] == 5_000   # 110k - 100k - 5k contributions = 5k market
    assert out["unattributed"] == 0


def test_attribution_signs_withdrawals_negative():
    from app.portfolio.attribution import compute_attribution
    txns = [_txn("2026-04-15", "transfer_out", -2_000)]
    out = compute_attribution(start_value=100_000, end_value=98_000, transactions=txns)
    assert out["withdrawals"] == -2_000  # signed: cash leaving
    assert out["contributions"] == 0
    assert out["market"] == 0  # exactly explained by the withdrawal
    assert out["unattributed"] == 0


def test_attribution_dividends_and_interest_combined_in_dividends_bucket():
    from app.portfolio.attribution import compute_attribution
    txns = [
        _txn("2026-04-10", "dividend", 25),
        _txn("2026-04-15", "interest", 5),
        _txn("2026-04-20", "reinvest", 0),  # zero net cash
    ]
    out = compute_attribution(start_value=10_000, end_value=10_100, transactions=txns)
    assert out["dividends"] == 30  # 25 + 5; reinvest amount is 0 by convention
    assert out["market"] == 70


def test_attribution_trades_with_cost_basis_uses_realized_pnl():
    """A buy of $100 then sell of $110: trades bucket = +$10 realized (no basis missing)."""
    from app.portfolio.attribution import compute_attribution
    txns = [
        _txn("2026-04-10", "buy",  -100, ticker="X", qty=1, price=100),
        _txn("2026-04-20", "sell", 110, ticker="X", qty=1, price=110, cost_basis_at_sell=100),
    ]
    out = compute_attribution(start_value=1_000, end_value=1_010, transactions=txns)
    # Cash impact of the round-trip is +$10; realized P&L is +$10.
    # In our convention: trades bucket = realized P&L for the period.
    assert out["trades"] == 10
    # Market for the unsold rest: 1010 - 1000 - 0 (flows) - 0 (div) - 10 (trades) = 0
    assert out["market"] == 0


def test_attribution_trades_without_basis_falls_back_to_cash_impact():
    """When cost_basis is missing, the trades bucket is the signed cash impact of all
    buy/sell rows, labelled in the result as needing-basis."""
    from app.portfolio.attribution import compute_attribution
    txns = [
        _txn("2026-04-10", "buy",  -1_000, ticker="X", qty=10, price=100),
        _txn("2026-04-20", "sell", 1_100, ticker="X", qty=10, price=110, cost_basis_at_sell=None),
    ]
    out = compute_attribution(start_value=10_000, end_value=10_500, transactions=txns)
    # Cash impact: -1000 + 1100 = +100. Without basis, trades = +100.
    assert out["trades"] == 100
    assert out["trades_has_basis"] is False
    assert out["market"] == 400  # 10_500 - 10_000 - 0 (flows) - 0 (div) - 100 (trades)


def test_attribution_surfaces_unattributed_when_inputs_dont_explain_change():
    """If sum of buckets != end - start, the residual goes to unattributed, not market."""
    from app.portfolio.attribution import compute_attribution
    # Pretend the user has txns + flows but the snapshot shows an unexplained jump.
    txns = [_txn("2026-04-15", "transfer_in", 1_000)]
    # No dividends, no trades. End − start − contributions = 9000. Suppose tolerance
    # is exceeded vs. a known-clean reference: we expose `unattributed` as the bucket.
    out = compute_attribution(
        start_value=100_000, end_value=110_000, transactions=txns,
        clean_market_estimate=8_000,  # caller can pass a reference (e.g. SPY-implied move)
    )
    # market = clean estimate; unattributed = residual
    assert out["market"] == 8_000
    assert out["unattributed"] == 1_000  # 110k - 100k - 1k contrib - 0 div - 0 trades - 8k market = 1k
    assert out["contributions"] == 1_000


def test_attribution_identity_holds_for_all_paths():
    """Internal identity: start + flows + market + dividends + trades + unattributed = end."""
    from app.portfolio.attribution import compute_attribution
    txns = [
        _txn("2026-04-10", "transfer_in", 2_000),
        _txn("2026-04-15", "buy", -500, ticker="X", qty=5, price=100),
        _txn("2026-04-20", "sell", 600, ticker="X", qty=5, price=120, cost_basis_at_sell=500),
        _txn("2026-04-25", "dividend", 12),
    ]
    out = compute_attribution(start_value=50_000, end_value=53_500, transactions=txns)
    total = (
        out["contributions"] + out["withdrawals"]
        + out["market"] + out["dividends"] + out["trades"] + out["unattributed"]
    )
    assert abs(total - (out["end_value"] - out["start_value"])) < 0.01
