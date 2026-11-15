from datetime import date

from app.engine.growth import compute_growth


def test_missing_account_history_is_not_zero():
    accounts = [{'id': 'a', 'type': 'checking', 'balance': 200}, {'id': 'b', 'type': 'debt', 'balance': -50}]
    result = compute_growth(accounts, [{'account_id': 'a', 'balance': 100, 'as_of': '2026-08-01'}], [], [], date(2026, 7, 10), date(2026, 10, 10))
    assert result['current']['net_worth'] == 150
    assert result['change'] is None
    assert result['series'][0]['net_worth'] is None


def test_debt_reduction_and_unrealized_gain_are_separate_from_contributions():
    accounts = [{'id': 'a', 'type': 'brokerage', 'balance': 150}, {'id': 'b', 'type': 'debt', 'balance': -20}]
    history = [{'account_id': 'a', 'balance': 100, 'as_of': '2026-07-10'}, {'account_id': 'b', 'balance': -50, 'as_of': '2026-07-10'}]
    snapshots = [
        {'account_id': 'a', 'snapshot_date': '2026-07-10', 'snapshot_holdings': [{'market_value': 100, 'cost_basis': 80}]},
        {'account_id': 'a', 'snapshot_date': '2026-10-10', 'snapshot_holdings': [{'market_value': 150, 'cost_basis': 100}]},
    ]
    transactions = [{'account_id': 'a', 'date': '2026-08-01', 'type': 'transfer_in', 'amount': 20}, {'account_id': 'a', 'date': '2026-08-02', 'type': 'buy', 'amount': -20}]
    result = compute_growth(accounts, history, snapshots, transactions, date(2026, 7, 10), date(2026, 10, 10))
    assert result['change'] == 80
    assert result['changes']['debt'] == 30
    assert result['investments']['net_contributions'] == 20
    assert result['investments']['unrealized']['value'] == 50
    assert result['investments']['unrealized_change'] == 30


def test_missing_basis_and_nonpositive_start_do_not_fabricate_metrics():
    accounts = [{'id': 'a', 'type': 'brokerage', 'balance': 100}]
    history = [{'account_id': 'a', 'balance': 0, 'as_of': '2026-07-10'}]
    snapshots = [{'account_id': 'a', 'snapshot_date': '2026-10-10', 'snapshot_holdings': [{'market_value': 100, 'cost_basis': None}]}]
    result = compute_growth(accounts, history, snapshots, [], date(2026, 7, 10), date(2026, 10, 10))
    assert result['percent_change'] is None
    assert result['investments']['unrealized']['value'] is None
    assert result['investments']['net_contributions'] is None


def test_partial_holdings_do_not_report_zero_unrealized():
    result = compute_growth([{'id': 'a', 'type': 'brokerage', 'balance': 100}], [],
        [{'account_id': 'a', 'snapshot_date': '2026-10-10', 'total_value': 100, 'cash_value': 0, 'snapshot_holdings': []}], [], None, date(2026, 10, 10))
    assert result['investments']['unrealized']['value'] is None


def test_growth_endpoint_scopes_to_authenticated_user(monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.middleware import get_current_user
    import app.engine.growth as growth
    import app.engine.router as router
    calls = []
    monkeypatch.setattr(router, '_db', lambda: 'db')
    monkeypatch.setattr(growth, 'load_growth', lambda db, uid, start, today: calls.append((uid, start)) or {'ok': True})
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id='owner')
    try:
        client = TestClient(app)
        assert client.get('/engine/growth?window=All').json() == {'ok': True}
        assert calls == [('owner', None)]
        assert client.get('/engine/growth?window=invalid').status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)
