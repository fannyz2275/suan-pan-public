from copy import deepcopy

import pytest

from app.engine.forecast_service import ForecastUpdate, load_forecast
from tests.forecast_fixture import FixtureDB, TODAY, UID


def test_overrides_persist_and_win_after_source_updates():
    db = FixtureDB()
    baseline = load_forecast(db, UID, today=TODAY)
    assert baseline['monthly_totals'] == {'income':5000, 'recurring_costs':1060, 'everyday_spending':500}
    assert baseline['projection'][2]['cash_p50'] == 24320
    assert baseline['projection'][-1]['wealth_p50'] == 65280
    update = ForecastUpdate(overrides={'goal:wedding':{'enabled':False}, 'history:everyday_spending:groceries':{'amount':700}})
    changed = load_forecast(db, UID, today=TODAY, update=update)
    assert changed['projection'][2]['cash_p50'] == 29720
    assert load_forecast(db, UID, today=TODAY) == changed
    db.tables['goals'][0]['target_amount'] = 20000
    assert next(i for i in load_forecast(db, UID, today=TODAY)['assumptions'] if i['id'] == 'goal:wedding')['enabled'] is False


def test_user_scoping_and_unknown_override_does_not_write():
    db = FixtureDB()
    before = deepcopy(db.tables)
    with pytest.raises(ValueError):
        load_forecast(db, UID, today=TODAY, update=ForecastUpdate(overrides={'goal:foreign':{'enabled':False}}))
    assert db.tables == before
    foreign = load_forecast(db, 'different-user', today=TODAY)
    assert foreign['starting']['net_worth'] == 0
    assert foreign['assumptions'] == []


def test_failed_save_does_not_return_success(monkeypatch):
    db = FixtureDB()
    from tests.forecast_fixture import FixtureQuery
    def fail(*args): raise RuntimeError('Write unavailable')
    monkeypatch.setattr(FixtureQuery, 'upsert', fail)
    with pytest.raises(RuntimeError, match='Write unavailable'):
        load_forecast(db, UID, today=TODAY, update=ForecastUpdate(overrides={'goal:wedding':{'enabled':False}}))


def test_current_month_only_history_is_not_a_zero_baseline():
    db = FixtureDB()
    db.tables['recurring_rules'] = []
    db.tables['transactions'] = [dict(id='t', user_id=UID, date='2026-10-01', amount=5000, category='income')]
    result = load_forecast(db, UID, today=TODAY)
    assert not result['data_quality']['has_history_baseline']
    assert not result['data_quality']['has_income']
    assert any('elapsed months' in w for w in result['warnings'])


def test_memory_override_survives_source_update_and_promotion_to_goal():
    db = FixtureDB()
    db.tables['goals'] = []
    load_forecast(db, UID, today=TODAY, update=ForecastUpdate(overrides={'memory:memory-wedding':{'enabled':False, 'amount':8000}}))
    db.tables['user_notes'][1]['provenance']['forecast_event']['amount'] = 9000
    result = load_forecast(db, UID, today=TODAY)
    item = next(i for i in result['assumptions'] if i['id'] == 'memory:memory-wedding')
    assert (item['enabled'], item['amount']) == (False, 8000)
    db.tables['goals'] = [dict(id='g', user_id=UID, name='Our Wedding', type='life_event', target_amount=9000, target_date='2026-12-01', is_active=True)]
    result = load_forecast(db, UID, today=TODAY)
    item = next(i for i in result['assumptions'] if i['id'] == 'goal:g')
    assert (item['enabled'], item['amount']) == (False, 8000)
    reset = load_forecast(db, UID, today=TODAY, update=ForecastUpdate(overrides={'goal:g':{}}))
    reloaded = load_forecast(db, UID, today=TODAY)
    assert reset == reloaded
    goal = next(i for i in reloaded['assumptions'] if i['id'] == 'goal:g')
    assert (goal['enabled'], goal['amount']) == (True, 9000)


def test_income_only_history_warns_that_spending_is_missing():
    db = FixtureDB()
    db.tables['recurring_rules'] = []
    db.tables['transactions'] = [dict(id='t', user_id=UID, date='2026-09-01', amount=5000, category='income')]
    result = load_forecast(db, UID, today=TODAY)
    assert result['data_quality']['has_history_baseline'] is False
    assert result['data_quality']['has_spending'] is False


def test_explicit_goal_link_preserves_override_when_names_differ():
    db = FixtureDB()
    db.tables['goals'] = []
    load_forecast(db, UID, today=TODAY, update=ForecastUpdate(overrides={'memory:memory-wedding':{'enabled':False}}))
    db.tables['goals'] = [dict(id='g', user_id=UID, name='Celebration', type='life_event', target_amount=6000, target_date='2026-12-01', is_active=True)]
    db.tables['user_notes'][1]['provenance']['forecast_event']['goal_id'] = 'g'
    result = load_forecast(db, UID, today=TODAY)
    assert next(i for i in result['assumptions'] if i['id'] == 'goal:g')['enabled'] is False


def test_mcp_forecast_matches_http_service(monkeypatch):
    import asyncio
    import json
    from app.mcp import server
    db = FixtureDB()
    monkeypatch.setattr(server, '_db', lambda: db)
    monkeypatch.setattr(server, 'load_forecast', lambda db, uid, **kwargs: load_forecast(db, uid, today=TODAY, **kwargs))
    result = asyncio.run(server.call_tool('get_financial_forecast', {'user_id':UID, 'months':12}))
    assert json.loads(result[0].text) == load_forecast(db, UID, today=TODAY)


def test_http_auth_validation_and_shared_forecast(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from app.engine import router
    from app.auth.middleware import get_current_user
    db = FixtureDB()
    app = FastAPI()
    app.include_router(router.router)
    monkeypatch.setattr(router, '_db', lambda: db)
    monkeypatch.setattr(router, 'load_forecast', lambda db, uid, **kwargs: load_forecast(db, uid, today=TODAY, **kwargs))
    with TestClient(app) as client:
        assert client.get('/engine/forecast').status_code in {401, 403}
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=UID)
        assert client.get('/engine/forecast?months=361').status_code == 422
        before = client.get('/engine/forecast').json()
        assert before == load_forecast(db, UID, today=TODAY)
        assert client.patch('/engine/forecast', json={'overrides':{'goal:wedding':{'frequency':'monthly'}}}).status_code == 422
        assert client.patch('/engine/forecast', json={'settings':{'invest_surplus':2}}).status_code == 422
        assert client.get('/engine/forecast').json() == before
        changed = client.patch('/engine/forecast', json={'overrides':{'goal:wedding':{'enabled':False}}})
        assert changed.status_code == 200
        assert client.get('/engine/forecast').json() == changed.json()
