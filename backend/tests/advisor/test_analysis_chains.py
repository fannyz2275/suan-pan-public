import pytest
from app.advisor.evidence.pipeline import FixtureAdapter, run_analysis
from tests.advisor.test_evidence_pipeline import Provider


FIXTURE = {'metrics': {
    'august_income': 100, 'september_income': 120, 'income_change': 20,
    'august_income_source_A': 80, 'september_income_source_A': 95,
    'august_income_source_B': 20, 'september_income_source_B': 25,
    'august_net_spending': 80, 'september_net_spending': 50, 'net_spending_change': -30,
    'august_money_kept': 20, 'september_money_kept': 70, 'money_kept_change': 50,
}, 'availability': {'aligned_wealth': False}}


def run(task, fixture=FIXTURE, answer=None):
    provider = Provider(plan={'task': task, 'requests': []},
                        answer=answer or {'blocks': [{'text': 'Review the recorded sources.'}]})
    return run_analysis('What drove the change?', [], {}, FixtureAdapter(fixture), provider)


def test_income_task_executes_dependencies_and_renders_omitted_contributors():
    result = run('income_change')
    assert [t['name'] for t in result['tool_trace']] == ['summary', 'contributors']
    assert 'A:' in result['answer'] and 'B:' in result['answer']
    assert 'change: $15.00' in result['answer']
    assert result['evidence']['answer_contract']['reconciled'] is True


def test_income_chain_detects_partial_sources_without_claiming_reconciliation():
    fixture = {**FIXTURE, 'metrics': {**FIXTURE['metrics'], 'september_income': 130, 'income_change': 30}}
    result = run('income_change', fixture)
    assert result['evidence']['answer_contract']['reconciled'] is False
    assert 'do not fully reconcile' in result['answer']


def test_wealth_chain_requires_unavailable_statement_and_signed_formula():
    result = run('wealth_change')
    assert 'Total wealth change is unavailable' in result['answer']
    assert 'income change ($20.00) minus spending change (-$30.00) = $50.00' in result['answer']
    assert 'aligned_wealth' in result['missing_requirements']


def test_wealth_chain_rejects_inconsistent_cashflow_identity():
    fixture = {**FIXTURE, 'metrics': {**FIXTURE['metrics'], 'money_kept_change': 99}}
    with pytest.raises(ValueError, match='Cash-flow reconciliation'):
        run('wealth_change', fixture)


def test_aligned_wealth_uses_balances_not_cash_surplus():
    fixture = {'metrics': {**FIXTURE['metrics'], 'august_net_worth': 500, 'september_net_worth': 510, 'net_worth_change': 10},
               'availability': {'aligned_wealth': True}}
    result = run('wealth_change', fixture)
    assert 'Total wealth changed by $10.00' in result['answer']
    assert 'not a reconciliation of total wealth' in result['answer']


def test_writer_cannot_replace_required_facts_with_invented_arithmetic():
    result = run('wealth_change', answer={'blocks': [{'text': 'Income plus spending equals {{money_kept_change}}.'}]})
    assert 'Income plus spending equals' not in result['answer']
    assert result['interpretation_status'] == 'withheld_numeric_restatement'


def test_disappearing_income_source_is_a_negative_contributor():
    fixture = {'metrics': {'august_income': 100, 'september_income': 60, 'income_change': -40,
                          'august_income_source_A': 60, 'september_income_source_A': 60,
                          'august_income_source_B': 40}}
    result = run('income_change', fixture)
    assert 'B: previous: $40.00; current: $0.00; change: -$40.00' in result['answer']
    assert result['evidence']['answer_contract']['reconciled'] is True


def test_current_income_summary_does_not_require_previous_period():
    fixture = {'metrics': {'september_income': 120, 'september_income_source_A': 120}}
    result = run('income_summary', fixture)
    assert 'September $120.00' in result['answer']
    assert 'attribution is incomplete' not in result['answer']
    assert result['evidence']['answer_contract']['reconciled'] is True
    assert 'previous:' not in result['answer']
    assert 'change:' not in result['answer']
    assert 'august_income_source_A' not in result['evidence']['metrics']


def test_chain_writer_preserves_candidate_guidance_under_fixed_contract():
    class Inspect(Provider):
        def complete(self, role, messages, **kwargs):
            if role == 'writer':
                assert 'Use plain language and short paragraphs.' in messages[0]['content']
            return super().complete(role, messages, **kwargs)
    run_analysis('Income?', [], {}, FixtureAdapter(FIXTURE),
                 Inspect(plan={'task': 'income_summary', 'requests': []}, answer={'blocks':[{'text':'Review the sources.'}]}),
                 candidate_prompt='Use plain language and short paragraphs.')


def test_missing_balance_values_override_true_availability_flag():
    result = run('wealth_change', {**FIXTURE, 'availability': {'aligned_wealth': True}})
    assert 'Total wealth change is unavailable' in result['answer']
    assert 'aligned_wealth' in result['missing_requirements']


def test_automatic_dependencies_are_not_redundant_model_requests():
    provider = Provider(plan={'task': 'income_change', 'requests': [
        {'tool': 'summary'}, {'tool': 'contributors', 'group': 'income_source', 'measure': 'absolute_change'}]},
        answer={'blocks':[{'text':'Review the sources.'}]})
    result = run_analysis('Income change?', [], {}, FixtureAdapter(FIXTURE), provider)
    assert result['redundant_calls'] == 0
    assert len(result['tool_trace']) == 2


def test_actual_duplicate_model_requests_still_count():
    provider = Provider(plan={'task':'income_change', 'requests':[{'tool':'summary'}, {'tool':'summary'}]},
                        answer={'blocks':[{'text':'Review the sources.'}]})
    result = run_analysis('Income change?', [], {}, FixtureAdapter(FIXTURE), provider)
    assert result['redundant_calls'] == 1


def test_long_interpretation_cannot_bury_required_facts():
    result = run('wealth_change', answer={'blocks':[{'text': 'Check available balances. ' * 30}]})
    assert 'Total wealth change is unavailable' in result['answer']
    assert 'Check available balances.' not in result['answer']
    assert result['interpretation_status'] == 'withheld_numeric_restatement'


def test_income_change_cannot_rank_an_unobserved_previous_month():
    fixture = {'metrics': {'september_income': 120, 'september_income_source_A': 120}}
    result = run('income_change', fixture)
    assert 'Income change and its contributors are unavailable' in result['answer']
    assert 'previous:' not in result['answer']
    assert result['evidence']['rankings'] == {}
