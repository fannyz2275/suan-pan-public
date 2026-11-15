from app.advisor.evidence.data import fixture_from_rows, month_scope
from app.advisor.evidence.registry import build_evidence


def test_refunds_transfers_and_missing_balances():
    scope = month_scope('2026-09')
    rows = [dict(account_id='a', amount=100, category='income', date='2026-09-03'),
            dict(account_id='a', amount=-20, category='food', date='2026-09-03'),
            dict(account_id='a', amount=5, category='food', date='2026-09-03'),
            dict(account_id='a', amount=-50, category='transfer', date='2026-09-03')]
    fixture = fixture_from_rows(scope, [{'id':'a'}], rows, [], [], [], [])
    assert fixture['metrics']['september_net_spending'] == '15.00'
    assert fixture['metrics']['september_money_kept'] == '85.00'
    assert fixture['metrics']['september_refund_candidate_count'] == '1.00'
    assert not fixture['availability']['aligned_wealth']
    build_evidence(fixture['metrics'])


def test_legacy_auto_pair_not_newly_identity_verified():
    rows = [dict(id='x', user_id='u', account_id='a', amount=-50, category='transfer', date='2026-09-03', transfer_status='auto_paired', transfer_group_id='g'),
            dict(id='y', user_id='u', account_id='b', amount=50, category='transfer', date='2026-09-03', transfer_status='auto_paired', transfer_group_id='g')]
    fixture = fixture_from_rows(month_scope('2026-09'), [{'id':'a'},{'id':'b'}], rows, [], [], [], [])
    assert fixture['metrics']['september_confirmed_pairs'] == '0.00'
    assert fixture['metrics']['september_unresolved_rows'] == '2.00'


def test_positive_debt_subtracted_and_wealth_tool_includes_values():
    from app.advisor.evidence.pipeline import FixtureAdapter
    from app.advisor.evidence.contracts import ToolRequest
    accounts = [{'id':'a','type':'checking'},{'id':'d','type':'debt'}]
    history = [dict(account_id=key,balance=value,as_of=day) for day in ('2026-08-31','2026-09-30')
               for key,value in [('a',1000),('d',200)]]
    fixture = fixture_from_rows(month_scope('2026-09'),accounts,[],[],history,[],[])
    assert fixture['metrics']['september_net_worth'] == '800.00'
    values,_ = FixtureAdapter(fixture).execute(ToolRequest(tool='wealth'))
    assert values['september_net_worth'] == '800.00'
    assert values['net_worth_change'] == '0.00'


def test_partial_portfolio_basis_is_not_complete():
    accounts = [{'id':'a','type':'brokerage'},{'id':'b','type':'retirement'}]
    snapshot = {'id':'s','account_id':'a','snapshot_date':'2026-09-30','cash_value':0}
    holding = {'snapshot_id':'s','ticker':'TEST','market_value':100,'cost_basis':80}
    fixture = fixture_from_rows(month_scope('2026-09'),accounts,[],[],[],[snapshot],[holding])
    assert not fixture['availability']['complete_cost_basis']
