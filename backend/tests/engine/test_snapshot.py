from app.engine.snapshot import compute_snapshot


def test_net_worth_basic():
    accounts = [
        {"type": "checking", "balance": 10000},
        {"type": "savings", "balance": 20000},
        {"type": "brokerage", "balance": 50000},
        {"type": "retirement", "balance": 80000},
        {"type": "property", "estimated_value": 400000, "balance": 0},
        {"type": "debt", "balance": -15000},
        {"type": "debt", "balance": -300000},
    ]
    snapshot = compute_snapshot(accounts)
    assert snapshot["liquid_assets"] == 30000        # checking(10k) + savings(20k)
    assert snapshot["investment_assets"] == 130000   # brokerage(50k) + retirement(80k)
    assert snapshot["non_current_assets"] == 400000  # property notional
    assert snapshot["total_liabilities"] == 315000
    assert snapshot["net_worth"] == 30000 + 130000 + 400000 - 315000  # 245000
    assert snapshot["liquid_net_worth"] == 30000 + 130000  # liquid + investments (excludes non-current)


def test_rsu_notional_value():
    accounts = [
        {"type": "rsu", "vested_shares": 100, "unvested_shares": 300, "grant_price": 50.0, "balance": 0},
    ]
    snapshot = compute_snapshot(accounts)
    assert snapshot["non_current_assets"] == 400 * 50.0


def test_business_equity_notional():
    accounts = [
        {"type": "business", "estimated_valuation": 1_000_000, "ownership_pct": 25.0, "balance": 0},
    ]
    snapshot = compute_snapshot(accounts)
    assert snapshot["non_current_assets"] == 250_000.0


def test_empty_accounts():
    snapshot = compute_snapshot([])
    assert snapshot["net_worth"] == 0
    assert snapshot["liquid_assets"] == 0


def test_property_falls_back_to_balance_when_estimated_value_is_null():
    accounts = [{"type": "property", "balance": 500_000, "estimated_value": None}]
    result = compute_snapshot(accounts)
    assert result["non_current_assets"] == 500_000


def test_property_uses_estimated_value_when_set():
    accounts = [{"type": "property", "balance": 400_000, "estimated_value": 600_000}]
    result = compute_snapshot(accounts)
    assert result["non_current_assets"] == 600_000


def test_property_returns_zero_when_estimated_value_is_explicitly_zero():
    accounts = [{"type": "property", "balance": 500_000, "estimated_value": 0}]
    result = compute_snapshot(accounts)
    assert result["non_current_assets"] == 0.0
