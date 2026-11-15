def test_cash_in_holdings_counted_once_and_basis_missing_not_zero():
    from .financial_evidence import holdings_summary
    result=holdings_summary([{'market_value':100,'cost_basis':80},{'market_value':50,'cost_basis':None}],10)
    assert result['holdings_value']==150
    assert result['portfolio_value']==160
    assert result['unrealized_gain_available'] is False


def test_same_security_across_accounts_is_one_concentration_position():
    from .financial_evidence import holdings_summary
    r=holdings_summary([{'ticker':'AAA','market_value':100}, {'ticker':'AAA','market_value':200},
                       {'ticker':'BBB','market_value':50}])
    assert r['holdings_count']==2
    assert r['largest_holding_percent']==85.71


def test_only_balanced_distinct_owned_pair_counts_once():
    from .financial_evidence import transfer_summary
    rows=[{'id':'a','account_id':'a','transfer_group_id':'g','transfer_status':'user_confirmed_internal','amount':-100},
          {'id':'b','account_id':'b','transfer_group_id':'g','transfer_status':'user_confirmed_internal','amount':100},
          {'id':'c','account_id':'a','transfer_group_id':None,'transfer_status':None,'amount':-40}]
    result=transfer_summary(rows,{'a','b'})
    assert result['confirmed_internal_moved_once']==100
    assert result['unresolved_rows']==1
    assert result['external_out']==0
    rows[1]['account_id']='a'
    assert transfer_summary(rows,{'a','b'})['confirmed_internal_moved_once']==0


def test_missing_boundary_cannot_be_replaced_with_current_balance():
    from .financial_evidence import aligned_wealth
    result=aligned_wealth([{'account_id':'a','as_of':'2026-10-11','balance':999}],{'a'},'2026-08-31','2026-09-30')
    assert not result['available']
    assert 'change' not in result


def test_refund_word_is_not_proof():
    from .financial_evidence import refund_summary
    r=refund_summary([{'amount':20,'description':'refund','category':'shopping'},
                      {'amount':30,'category':'transfer'}, {'amount':40,'category':'income'}])
    assert r['candidate_amount']==20
    assert r['verified_amount']==0


def test_aligned_wealth_uses_exact_signed_values():
    from .financial_evidence import aligned_wealth
    rows=[{'account_id':a,'as_of':d,'balance':v} for a,d,v in [
        ('a','2026-08-31',100),('a','2026-09-30',120),
        ('b','2026-08-31',-30),('b','2026-09-30',-20)]]
    assert aligned_wealth(rows,{'a','b'},'2026-08-31','2026-09-30')['change']==30
