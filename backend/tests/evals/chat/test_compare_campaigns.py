from tests.evals.chat.compare_campaigns import baseline_rescore


def test_old_necessary_call_is_rescored_without_penalty():
    old = {'scores':dict(accuracy=1,directness=1,concision=1,cost=1,latency=1,tools=.5),
           'hard_failures':[], 'turns':[{'tool_trace':[{'name':'get_metrics'}]}]}
    assert baseline_rescore(old)['score'] == 1
    old['turns'][0]['evaluator_errors'] = ['invalid_judge']
    assert baseline_rescore(old)['score'] is None
