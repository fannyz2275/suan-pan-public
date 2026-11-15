"""Synthetic, in-memory data shared by HTTP and Playwright forecast tests."""
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

UID = '00000000-0000-4000-8000-000000000001'
TODAY = date(2026, 10, 31)


def fixture_tables():
    rules = []
    for i, (name, amount, direction) in enumerate([('Payroll', 5000, 'income'), ('Rent', 1000, 'expense'), ('Internet', 60, 'expense')], 2):
        rules.append(dict(id=f'00000000-0000-4000-8000-{i:012}', user_id=UID, keyword=name,
                          normalized_key_pattern=name.lower(), amount_min=amount, amount_max=amount,
                          amount_median=amount, frequency='monthly', direction=direction, confidence=1,
                          status='user_confirmed', source='heuristic', last_seen_date='2026-09-01'))
    rows = []
    for month in ['2026-07', '2026-08', '2026-09']:
        for i, (name, amount, category) in enumerate([('Payroll', 5000, 'income'), ('Rent', -1000, 'housing'), ('Internet', -60, 'utilities'), ('Food', -500, 'groceries')]):
            rows.append(dict(id=f'{month}-{i}', user_id=UID, account_id='cash', date=month+'-01',
                             description=name, amount=amount, category=category, transfer_status=None))
    return {
        'accounts':[dict(id='cash', user_id=UID, name='Checking', type='checking', balance=20000, is_active=True),
                    dict(id='invest', user_id=UID, name='Brokerage', type='brokerage', balance=10000, is_active=True)],
        'goals':[dict(id='wedding', user_id=UID, name='Wedding', type='life_event', target_amount=6000,
                      current_progress=2000, target_date='2026-12-01', is_active=True, status='on_track', feasibility_score=100)],
        'transactions':rows,
        'recurring_rules':rules,
        'user_notes':[
            dict(id=str(uuid5(NAMESPACE_URL, f'suan-pan:{UID}:forecast-settings')), user_id=UID,
                 provenance={'settings':{'annual_return':0, 'annual_volatility':0, 'cash_reserve':0, 'invest_surplus':0}}),
            dict(id='memory-wedding', user_id=UID, provenance={'forecast_event':{'label':'Wedding', 'amount':6000, 'month':'2026-12'}}),
            dict(id='memory-vacation', user_id=UID, provenance={'forecast_event':{'label':'Vacation', 'amount':None, 'month':None}}),
        ],
    }


class FixtureDB:
    def __init__(self):
        self.tables = fixture_tables()

    def table(self, name):
        return FixtureQuery(self, name)


class FixtureQuery:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.bounds, self.payload = db, name, [], None, None

    def select(self, _): return self
    def eq(self, field, value):
        self.filters.append((field, value))
        return self
    def order(self, _): return self
    def range(self, start, end):
        self.bounds = (start, end + 1)
        return self
    def upsert(self, payload):
        self.payload = payload
        return self
    def execute(self):
        rows = self.db.tables[self.name]
        if self.payload:
            existing = next((r for r in rows if r['id'] == self.payload['id']), None)
            if existing is not None:
                existing.update(deepcopy(self.payload))
            else:
                rows.append(deepcopy(self.payload))
            return SimpleNamespace(data=[deepcopy(self.payload)])
        result = [deepcopy(r) for r in rows if all(r.get(k) == v for k, v in self.filters)]
        if self.bounds:
            result = result[self.bounds[0]:self.bounds[1]]
        return SimpleNamespace(data=result)
