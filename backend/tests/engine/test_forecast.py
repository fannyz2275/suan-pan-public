from datetime import date

import pytest

from app.engine.forecast import build_assumptions, project_forecast, ForecastSettings
from app.engine.recurring.schema import RecurringRule


TODAY = date(2026, 10, 12)
UID = '00000000-0000-4000-8000-000000000001'


def fixture_data():
    accounts = [dict(id='cash', type='checking', balance=20000),
                dict(id='invest', type='brokerage', balance=10000)]
    rules = [RecurringRule(id='00000000-0000-4000-8000-000000000002', user_id=UID,
        keyword='Rent', normalized_key_pattern='rent', amount_min=1000, amount_max=1000,
        amount_median=1000, frequency='monthly', direction='expense', confidence=1,
        status='user_confirmed', source='heuristic', last_seen_date='2026-09-01')]
    transactions = []
    for month in ['2026-07', '2026-08', '2026-09']:
        for name, amount, category in [('Salary', 5000, 'income'), ('Rent', -1000, 'housing'), ('Food', -500, 'groceries')]:
            transactions.append(dict(id=f'{month}-{name}', date=f'{month}-01', description=name,
                                     amount=amount, category=category, account_id='cash'))
    goals = [dict(id='wedding', name='Wedding', type='life_event', target_amount=6000,
                  current_progress=2000, target_date='2026-12-01')]
    return accounts, transactions, rules, goals


def assumptions():
    accounts, transactions, rules, goals = fixture_data()
    return accounts, build_assumptions(transactions, rules, goals, [], today=TODAY)


def test_recurring_and_residuals_are_disjoint():
    _, items = assumptions()
    assert sum(i.monthly_amount for i in items if i.group == 'recurring_costs') == 1000
    assert sum(i.monthly_amount for i in items if i.group == 'everyday_spending') == 500
    assert sum(i.monthly_amount for i in items if i.group == 'income') == 5000


def test_wedding_cash_and_wealth_reconcile_and_toggle():
    accounts, items = assumptions()
    settings = ForecastSettings(annual_return=0, annual_volatility=0, invest_surplus=0, cash_reserve=0)
    result = project_forecast(accounts, items, settings, months=3, today=TODAY)
    assert [r['cash_p50'] for r in result['projection']] == [23500, 21000, 24500]
    assert result['projection'][-1]['wealth_p50'] == 34500
    assert result['goals'][0]['funding_probability'] == 1
    wedding = next(i for i in items if i.id == 'goal:wedding')
    wedding.enabled = False
    without = project_forecast(accounts, items, settings, months=3, today=TODAY)
    assert without['projection'][-1]['wealth_p50'] - result['projection'][-1]['wealth_p50'] == 6000


def test_investment_transfer_never_creates_wealth_and_seed_is_repeatable():
    accounts, items = assumptions()
    settings = ForecastSettings(annual_return=0, annual_volatility=0, invest_surplus=1, cash_reserve=0)
    result = project_forecast(accounts, items, settings, months=3, today=TODAY)
    assert result['projection'][-1]['wealth_p50'] == 34500
    assert result == project_forecast(accounts, items, settings, months=3, today=TODAY)
    for row in result['projection']:
        assert row['wealth_p50'] == pytest.approx(row['cash_p50'] + row['investments_p50'])


def test_memory_event_deduplicates_goal_and_incomplete_event_is_visible():
    _, txns, rules, goals = fixture_data()
    notes = [dict(id='n1', provenance={'forecast_event': {'label':'Wedding', 'amount':6000, 'month':'2026-12'}}),
             dict(id='n2', provenance={'forecast_event': {'label':'Vacation', 'amount':None, 'month':None}})]
    items = build_assumptions(txns, rules, goals, notes, today=TODAY)
    assert len([i for i in items if i.label == 'Wedding']) == 1
    vacation = next(i for i in items if i.label == 'Vacation')
    assert vacation.reason and vacation.amount is None


def test_exclude_transfers_partial_future_months_and_net_refunds():
    _, txns, rules, goals = fixture_data()
    for month in ['2026-07', '2026-08', '2026-09']:
        txns += [dict(id=month+'refund', date=month+'-02', amount=100, category='groceries', description='refund'),
                 dict(id=month+'transfer', date=month+'-03', amount=9999, category='income', transfer_status='user_confirmed_internal')]
    txns += [dict(id='partial', date='2026-10-01', amount=9999, category='income'),
             dict(id='future', date='2027-01-01', amount=9999, category='income')]
    items = build_assumptions(txns, rules, goals, [], today=TODAY)
    assert sum(i.monthly_amount for i in items if i.group == 'income') == 5000
    assert sum(i.monthly_amount for i in items if i.group == 'everyday_spending') == 400


def test_savings_goal_reserves_without_spending_or_double_allocating():
    accounts, _, _, _ = fixture_data()
    goals = [dict(id=str(i), name=f'Savings {i}', type='savings', target_amount=18000, target_date='2026-11-01') for i in range(2)]
    items = build_assumptions([], [], goals, [], today=TODAY)
    result = project_forecast(accounts, items, ForecastSettings(annual_return=0, annual_volatility=0, invest_surplus=0), months=1, today=TODAY)
    assert result['projection'][0]['wealth_p50'] == 30000
    assert [g['funding_probability'] for g in result['goals']] == [1, 0]


def test_retirement_is_not_used_to_fund_wedding():
    _, items = assumptions()
    accounts = [dict(type='checking', balance=0), dict(type='retirement', balance=100000)]
    result = project_forecast(accounts, items, ForecastSettings(annual_return=0, annual_volatility=0, invest_surplus=0), months=2, today=TODAY)
    # 2 * 3500 surplus covers the 6000 wedding, without touching retirement.
    assert result['projection'][-1]['cash_p50'] == 1000
    assert result['projection'][-1]['investments_p50'] == 100000


def test_nonfinite_and_excessive_parameters_rejected():
    with pytest.raises(ValueError):
        ForecastSettings(annual_return=float('nan'))
    with pytest.raises(ValueError):
        ForecastSettings(invest_surplus=2)


def test_wedding_alias_deduplicates_but_distinct_events_remain():
    _, txns, rules, goals = fixture_data()
    goals[0]['name'] = 'Our wedding'
    notes = [dict(id='n1', provenance={'forecast_event':{'label':'Wedding', 'amount':6000, 'month':'2026-12'}}),
             dict(id='n2', provenance={'forecast_event':{'label':"Sister wedding", 'amount':2000, 'month':'2027-04'}})]
    items = build_assumptions(txns, rules, goals, notes, today=TODAY)
    assert len([i for i in items if i.group == 'planned_spending']) == 2


def test_debt_payment_reports_effective_amount_not_larger_target():
    accounts = [dict(type='checking', balance=20000), dict(type='debt', balance=-5000)]
    goals = [dict(id='debt', name='Clear debt', type='debt_payoff', target_amount=100000, target_date='2026-11-01')]
    items = build_assumptions([], [], goals, [], today=TODAY)
    result = project_forecast(accounts, items, ForecastSettings(annual_return=0, annual_volatility=0), months=1, today=TODAY)
    assert result['goals'][0]['amount'] == 5000
    assert result['goals'][0]['target_amount'] == 100000
    assert result['projection'][0]['wealth_p50'] == 15000


def test_distinct_memory_event_does_not_disappear_behind_same_named_goal():
    goals = [dict(id='g', name='Vacation', type='life_event', target_amount=2000, target_date='2027-03-01')]
    notes = [dict(id='n', provenance={'forecast_event':{'label':'Vacation', 'amount':4000, 'month':'2027-08', 'new_event':True}})]
    items = build_assumptions([], [], goals, notes, today=TODAY)
    assert len(items) == 2
    assert sum(i.amount for i in items) == 6000


def test_calendar_cadence_and_monthly_equivalents():
    from app.engine.forecast import Assumption, _scheduled_amount
    salary = Assumption(id='s', label='Payroll', group='income', source='recurring', amount=2000,
                        frequency='biweekly', anchor=date(2026, 10, 2))
    assert salary.monthly_amount == 4333.33
    assert _scheduled_amount(salary, date(2026, 10, 1)) == 6000
    assert _scheduled_amount(salary, date(2026, 11, 1)) == 4000
    annual = Assumption(id='a', label='Insurance', group='recurring_costs', source='recurring', amount=1200,
                        frequency='annual', anchor=date(2026, 5, 31))
    assert annual.monthly_amount == 100
    assert _scheduled_amount(annual, date(2027, 5, 1)) == 1200
    assert _scheduled_amount(annual, date(2027, 6, 1)) == 0


def test_horizon_prefix_and_stochastic_net_worth_reconciliation():
    accounts, items = assumptions()
    settings = ForecastSettings(cash_reserve=1000, invest_surplus=0.5)
    short = project_forecast(accounts, items, settings, months=12, today=TODAY)
    long = project_forecast(accounts, items, settings, months=60, today=TODAY)
    assert short['projection'] == long['projection'][:12]
    for row in long['projection']:
        assert row['wealth_p10'] <= row['wealth_p50'] <= row['wealth_p90']
        assert row['contribution'] <= max(0, row['income'] - row['spending']) * settings.invest_surplus
    r = long['reconciliation']
    assert r['ending_wealth_p50'] == pytest.approx(r['starting_wealth'] + r['income'] - r['spending'] + r['investment_gains_p50'], abs=0.01)


def test_rejected_recurring_and_disabled_active_rules_do_not_reappear_in_residuals():
    from app.engine.forecast import apply_overrides
    _, txns, rules, goals = fixture_data()
    items = build_assumptions(txns, rules, goals, [], today=TODAY)
    disabled = apply_overrides(items, {items[0].id:{'enabled':False}}, today=TODAY)
    assert sum(i.monthly_amount for i in disabled if i.group == 'everyday_spending') == 500
    rules[0].status = 'user_rejected'
    rejected = build_assumptions(txns, rules, goals, [], today=TODAY)
    assert sum(i.monthly_amount for i in rejected if i.group == 'everyday_spending') == 1500
