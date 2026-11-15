from tests.evals.chat.evidence_scoring_v3 import assess_v3, tool_efficiency


def test_judge_error_is_unscorable():
    result = assess_v3(answer='test', turn={}, judgement=None, references=[])
    assert result['scorable'] is False
    assert result['scores'] is None
    assert result['evaluator_errors']


def test_valid_number_reference_and_missing_claim():
    turn = {'expected':{'september_income':100}, 'checks':{}}
    judge = {'directness':100,'concision':100,'checks':{}}
    assert assess_v3('Income $100.',turn,judge,['september_income'])['scores']['accuracy'] == 1
    result = assess_v3('Unavailable.',turn,judge,[])
    assert result['scores']['accuracy'] == 0
    assert 'missing_required_numeric_claim' in result['hard_failures']


def test_necessary_tools_not_penalized():
    assert tool_efficiency(0) == 1
    assert tool_efficiency(1) == 2/3
    assert tool_efficiency(3) == 0


def test_tool_number_is_checked_against_independent_oracle():
    result = assess_v3('Income $10.', {'expected':{'september_income':100}},
                       {'directness':100,'concision':100}, ['september_income'], {'september_income':'10.00'})
    assert result['scores']['accuracy'] == 0
    assert 'incorrect_numeric_claim' in result['hard_failures']


def test_missing_semantic_check_unscorable_not_advisor_error():
    result = assess_v3('Answer',{'checks':{'scope':'correct scope'}},
                       {'directness':100,'concision':100,'checks':{}},[])
    assert result['scores'] is None
    assert result['hard_failures'] == []
