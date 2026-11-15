"""Evaluate the actual shared planner/executor/writer pipeline."""
import json
from app.advisor.evidence.pipeline import run_analysis, FixtureAdapter
from .offline_control import efficiency, aggregate
from .evidence_scoring_v3 import assess_v3, tool_efficiency


class EvaluationProvider:
    def __init__(self, transport, question_id, prefix):
        self.transport, self.question_id, self.prefix = transport, question_id, prefix
        self.records = []

    def complete(self, role, messages, *, max_tokens, response_format=None):
        # Existing frozen transport already supports these exact models. Preserve it.
        transport_role = {'planner':'judge','writer':'advisor','judge':'judge','memory':'memory'}[role]
        call_id = f'{self.prefix}:{len(self.records)}'
        response = self.transport.complete(self.question_id,call_id,transport_role,messages,
            max_tokens=max_tokens,reasoning_effort='none' if role == 'writer' else 'low',
            response_format=response_format or {'type':'json_object'})
        self.records.append({'call_id':call_id,'role':role,**response['_telemetry']})
        try:
            return json.loads(response['choices'][0]['message']['content'])
        except (ValueError,KeyError,TypeError):
            # A completed malformed response has known cost; never issue hidden retries.
            return None


def memory_probe(scenario, setup, provider):
    preferences, events = {}, []
    if not scenario.get('acquisition'): return preferences, events
    payload = provider.complete('memory',[
        {'role':'system','content':setup['memory_prompt'] + '\nReturn {"updates":[{"key":"style|detail|language","value":"preference","quote":"exact user quote","op":"update|delete"}]}. Preserve corrections in order. Never store financial facts.'},
        {'role':'user','content':json.dumps(scenario['acquisition'])}], max_tokens=1024)
    if not isinstance(payload,dict) or not isinstance(payload.get('updates'),list):
        return {}, [{'accepted':False,'error':'malformed_memory'}]
    for update in payload['updates']:
        if not isinstance(update,dict):
            events.append({'accepted':False}); continue
        key, value, quote, op = [update.get(k) for k in ('key','value','quote','op')]
        accepted = (key in setup['memory_policy']['allowed_keys'] and op in {'update','delete'}
                    and isinstance(quote,str) and bool(quote) and any(quote in s for s in scenario['acquisition'])
                    and (op == 'delete' or isinstance(value,str) and 0 < len(value) <= 200))
        if accepted and op == 'update' and key not in preferences and len(preferences) >= setup['memory_policy']['max_items']:
            accepted = False
        if accepted:
            if op == 'delete': preferences.pop(key,None)
            else: preferences[key] = value
        events.append({**update,'accepted':accepted})
    return preferences, events


def run_conversation(scenario, setup, transport, question_id, call_prefix):
    provider = EvaluationProvider(transport,question_id,call_prefix)
    preferences, memory_events = memory_probe(scenario,setup,provider)
    history, turns, hard_failures, evaluator_errors = [], [], [], []
    for index, turn in enumerate(scenario['turns']):
        failures = []
        start = len(provider.records)
        try:
            result = run_analysis(turn['question'],history,{'preferences':preferences},FixtureAdapter(scenario['fixture']),provider,
                                  candidate_prompt=setup.get('response_prompt',''))
        except ValueError as exc:
            result = {'answer':'Analysis could not be validated.', 'references':[], 'tool_trace':[],
                      'tool_latency':0, 'redundant_calls':0, 'validation_error':str(exc)}
            failures.append('pipeline_validation')
        answer = result['answer']
        judge = provider.complete('judge',[
            {'role':'system','content':'Evaluate this financial answer. Return JSON with directness and concision scored 0..100, and checks: {rule_id: {passed: boolean, reason: string}}. Return EVERY supplied check even if not applicable (passed true). Evaluate semantics, not numeric-span extraction. A supported concise answer is 100. A partial answer is 50. Honest unavailable evidence can be fully direct. Unsupported ownership/intent/causal claims fail. Do not treat a suggested thing to verify as a fact. No extra prose.'},
            {'role':'user','content':json.dumps({'question':turn['question'],'answer':answer,'history':history[-6:],
                'evidence':scenario['fixture'],'checks':turn.get('checks',{})})}], max_tokens=2048)
        assessment = assess_v3(answer,turn,judge,result['references'],
            {k:v['value'] for k,v in result.get('evidence',{}).get('metrics',{}).items()})
        failures += assessment['hard_failures']
        if result.get('validation_error') and assessment['scores'] is not None:
            assessment['scores']['accuracy'] = 0
        if any(preferences.get(k) != v for k,v in turn.get('expected_memory',{}).items()):
            failures.append('memory_mismatch')
        if turn.get('required_tools') and not result['tool_trace']: failures.append('missing_required_tool')
        turns.append({'question':turn['question'],'answer':answer, **assessment, 'hard_failures':failures,
                      'result':result,'judge':judge,'calls':provider.records[start:]})
        history.extend([{'role':'user','content':turn['question']},{'role':'assistant','content':answer}])
        hard_failures += [f'turn_{index}:{f}' for f in failures]
        evaluator_errors += [f'turn_{index}:{e}' for e in assessment['evaluator_errors']]
    scorable = not evaluator_errors
    operational = [c for c in provider.records if c['role'] != 'judge']
    latency = sum(c['latency_seconds'] for c in operational if c['role'] != 'memory') + sum(t['result']['tool_latency'] for t in turns)
    cost = sum(c['cost_microusd'] for c in operational) / 1e6
    redundant = sum(t['result']['redundant_calls'] for t in turns)
    scores = None
    if scorable:
        scores = {k:sum(t['scores'][k] for t in turns)/len(turns) for k in ('accuracy','directness','concision')}
        scores.update(cost=efficiency(cost,**scenario['budgets']['cost']),
                      latency=efficiency(latency,**scenario['budgets']['latency']),tools=tool_efficiency(redundant))
    return {'scores':scores,'scorable':scorable,'score':aggregate(scores) if scores else None,
            'passed':bool(scores and aggregate(scores) >= .95 and not hard_failures),
            'hard_failures':hard_failures,'evaluator_errors':evaluator_errors,'turns':turns,
            'valid_turns':sum(t['scorable'] for t in turns),'total_turns':len(turns),
            'memory_events':memory_events,'preferences':preferences,'call_records':provider.records,
            'telemetry':{'operational_cost':cost,'operational_latency':latency,'redundant_calls':redundant,
                         'tool_calls':sum(len(t['result']['tool_trace']) for t in turns)}}
