"""Metric-reference accuracy plus semantic judging, with explicit evaluator validity."""
import math
import re


def canonical(key):
    return key.replace('_unresolved_transfer_rows', '_unresolved_rows')


def tool_efficiency(redundant_calls):
    return max(0, (3 - redundant_calls) / 3)


def assess_v3(answer, turn, judgement, references, metric_values=None):
    errors, failures = [], []
    scores = {}
    judgement = judgement if isinstance(judgement, dict) else {}
    for key in ('directness','concision'):
        value = judgement.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 100:
            errors.append('invalid_' + key)
        else: scores[key] = value / 100
    checks = judgement.get('checks', {})
    for rule in turn.get('checks', {}):
        check = checks.get(rule) if isinstance(checks,dict) else None
        if not isinstance(check,dict) or type(check.get('passed')) is not bool or not isinstance(check.get('reason'),str):
            errors.append('missing_semantic_check:' + rule)
        elif not check['passed']: failures.append('semantic:' + rule)
    required = {canonical(k) for k in turn.get('expected', {})}
    mentioned = {canonical(k) for k in references}
    incorrect = set()
    if metric_values is not None:
        oracle = {canonical(k):v for k,v in {**turn.get('references',{}),**turn.get('expected',{})}.items()}
        for key in references:
            if canonical(key) not in oracle:
                errors.append('missing_numeric_oracle:' + key)
                continue
            value = metric_values.get(key)
            expected = oracle[canonical(key)]
            try:
                if value is None or not math.isclose(float(value),float(expected),rel_tol=0,abs_tol=.005):
                    incorrect.add(canonical(key))
            except (TypeError,ValueError): incorrect.add(canonical(key))
        if incorrect: failures.append('incorrect_numeric_claim')
    missing = required - mentioned
    if missing: failures.append('missing_required_numeric_claim')
    scores['accuracy'] = len(mentioned - incorrect) / len(required | mentioned) if required | mentioned else 1.
    if 'concision' in scores:
        words = len(answer.split())
        paragraph = max((len(p.split()) for p in re.split(r'\n\s*\n',answer)), default=0)
        scores['concision'] = min(scores['concision'],120/max(120,words),60/max(60,paragraph))
    return {'scorable':not errors,'scores':None if errors else scores,
            'evaluator_errors':errors,'hard_failures':failures,'missing_metrics':sorted(missing)}
