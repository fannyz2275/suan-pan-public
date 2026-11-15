import pytest
from app.advisor.evidence.pipeline import run_analysis, FixtureAdapter
from app.advisor.evidence.rendering import render_answer


FIXTURE = {'metrics': {'september_income': 100, 'august_income': 90, 'income_change': 10},
           'period': 'September versus August', 'availability': {}}


class Provider:
    def __init__(self, plan=None, answer=None):
        self.roles = []
        self.plan = plan or {'requests':[{'tool':'summary'}]}
        self.answer = answer or {'blocks':[{'text':'Income was {{september_income}}.'}]}

    def complete(self, role, messages, **kwargs):
        self.roles.append(role)
        if role == 'planner':
            assert kwargs['response_format']['type'] == 'json_schema'
            assert kwargs['response_format']['json_schema']['schema']['additionalProperties'] is False
        return self.plan if role == 'planner' else self.answer


def test_two_calls_and_backend_rendering():
    p = Provider()
    result = run_analysis('Income?', [], {}, FixtureAdapter(FIXTURE), p)
    assert p.roles == ['planner', 'writer']
    assert result['answer'] == 'Income was $100.00.'
    assert result['references'] == ['september_income']


def test_unknown_tool_stops_before_writer():
    p = Provider(plan={'requests':[{'tool':'delete_goal'}]})
    with pytest.raises(ValueError):
        run_analysis('Income?', [], {}, FixtureAdapter(FIXTURE), p)
    assert p.roles == ['planner']


def test_duplicate_requests_are_not_executed_twice():
    p = Provider(plan={'requests':[{'tool':'summary'}, {'tool':'summary'}]})
    result = run_analysis('Income?', [], {}, FixtureAdapter(FIXTURE), p)
    assert result['redundant_calls'] == 1
    assert len(result['tool_trace']) == 1


def test_writer_must_reference_metrics():
    with pytest.raises(ValueError):
        render_answer({'blocks':[{'text':'Income was $1,250.'}]}, {'metrics':{}, 'rankings':{}})
    with pytest.raises(ValueError):
        render_answer({'blocks':[{'text':'Income was {{invented}}.'}]}, {'metrics':{}, 'rankings':{}})


def test_ranked_block_cannot_reorder_results():
    fixture = {'metrics': {'september_merchant_A': 255, 'august_merchant_A':0,
                           'september_merchant_Z':285.78, 'august_merchant_Z':0}}
    p = Provider(plan={'requests':[{'tool':'contributors','group':'merchant','measure':'current','limit':2}]},
                 answer={'blocks':[{'ranking':'merchant:current:2'}]})
    result = run_analysis('Top merchants?', [], {}, FixtureAdapter(fixture), p)
    assert result['answer'].index('Z:') < result['answer'].index('A:')


def test_period_or_scope_override_rejected():
    p = Provider(plan={'requests':[{'tool':'summary', 'user_id':'other'}]})
    with pytest.raises(ValueError):
        run_analysis('income', [], {}, FixtureAdapter(FIXTURE), p)


def test_frozen_fixture_cannot_silently_change_month():
    p = Provider(plan={'month':'2026-07','requests':[{'tool':'summary'}]})
    with pytest.raises(ValueError):
        run_analysis('July income', [], {}, FixtureAdapter(FIXTURE), p)


def test_live_adapter_period_is_honored():
    class ScopedAdapter(FixtureAdapter):
        def with_month(self, month):
            assert month == '2026-07'
            return FixtureAdapter({'metrics':{'july_income':200},'scope':{'month':month}})
    p = Provider(plan={'month':'2026-07','requests':[{'tool':'summary'}]},answer={'blocks':[{'text':'Income {{july_income}}.'}]})
    result = run_analysis('July income', [], {}, ScopedAdapter(FIXTURE), p)
    assert result['answer'] == 'Income $200.00.'


def test_contributor_plan_has_summary_dependency():
    fixture = {'metrics':{'september_income':100,'august_income':90,'income_change':10,
                          'september_income_source_A':100,'august_income_source_A':90}}
    p = Provider(plan={'requests':[{'tool':'contributors','group':'income_source'}]})
    result = run_analysis('Explain income change',[],{},FixtureAdapter(fixture),p)
    assert 'income_change' in result['evidence']['metrics']
    assert any(c['name']=='summary' for c in result['tool_trace'])


def test_frozen_scope_does_not_offer_month_selection_to_model():
    class InspectProvider(Provider):
        def complete(self,role,messages,**kwargs):
            if role == 'planner':
                schema=kwargs['response_format']['json_schema']['schema']
                assert 'month' not in schema['properties']
                assert 'NEVER include month' in messages[0]['content']
            return super().complete(role,messages,**kwargs)
    run_analysis('Income?',[],{},FixtureAdapter(FIXTURE),InspectProvider())
