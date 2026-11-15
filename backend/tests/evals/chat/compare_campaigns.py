"""Read cached outputs only. Never pay to rejudge or rewrite either campaign."""
import argparse
import json
from pathlib import Path
from .offline_control import aggregate
from .evidence_scoring_v3 import tool_efficiency


def baseline_rescore(round_result):
    turns = round_result['turns']
    if any(t.get('evaluator_errors') or any(f.startswith('evaluator:') for f in t.get('hard_failures',[])) for t in turns):
        return {'score':None,'passed':False,'scorable':False}
    redundant = 0
    for turn in turns:
        seen = set()
        for call in turn.get('tool_trace',[]):
            request = call.get('request',{}).get('function',{})
            args = request.get('arguments','{}')
            try: args = json.loads(args)
            except (TypeError,ValueError): pass
            key = json.dumps([call['name'],args],sort_keys=True)
            if key in seen: redundant += 1
            seen.add(key)
    scores = dict(round_result['scores'])
    scores['tools'] = tool_efficiency(redundant)
    score = aggregate(scores)
    return {'scores':scores,'score':score,'scorable':True,'passed':score >= .95 and not round_result['hard_failures']}


def compare(old,new):
    old_by_id = {q['question']:q for q in old['questions']}
    results = []
    for question in new['questions']:
        before = old_by_id[question['question']]
        for after in question['rounds']:
            prior = before['rounds'][after['number']-1]
            adjusted = baseline_rescore(prior)
            results.append({'question':question['question'],'round':after['number'],
                'old_native_score':prior['score'],'old_adjusted':adjusted,
                'new_score':after['score'],'new_passed':after['passed'],'new_scorable':after['scorable'],
                'matched_score_delta':after['score']-adjusted['score'] if after['scorable'] and adjusted['scorable'] else None,
                'old_failures':prior['hard_failures'],'new_failures':after['hard_failures'],
                'new_evaluator_errors':after['evaluator_errors']})
    return {'comparisons':results,'budget':new['budget'],
            'method':'Cached baseline retains numerical and semantic judgments; tool-efficiency and evaluator validity use revised rules. No paid rejudging. Claim extraction and judge prompts differ, so adjusted scores are not a controlled model-only comparison.',
            'same_questions':all([t['question'] for t in old_by_id[q['question']]['rounds'][0]['turns']] ==
                                 [t['question'] for t in q['rounds'][0]['turns']] for q in new['questions'] if q['rounds'])}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--old',type=Path,required=True); p.add_argument('--new',type=Path,required=True)
    a = p.parse_args()
    print(json.dumps(compare(json.loads(a.old.read_text()),json.loads(a.new.read_text())),indent=2))
