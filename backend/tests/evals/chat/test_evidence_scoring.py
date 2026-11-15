import pytest


def test_markup_repeated_numbers_words_lists_and_dates():
    from .evidence_scoring import extract_numbers
    spans = extract_numbers('September 2026\n1. **Income: $100.00**\nAgain $100.00; one refund. On 2026-09-30.')
    assert [s['value'] for s in spans] == [100, 100, 1]
    assert len({s['id'] for s in spans}) == 3


def test_signed_decrease_and_explicit_approximation():
    from .evidence_scoring import assess, extract_numbers
    answer = 'Spending fell by about $51.'
    turn = {'expected': {'change': -50.72}, 'references': {}}
    spans = extract_numbers(answer)
    result = assess(answer, turn, {'directness': 100, 'concision': 100,
        'claims': [{'id': spans[0]['id'], 'keys': ['change']}], 'checks': {}})
    assert not result['hard_failures']
    exact = assess(answer.replace('about ', ''), turn, {'directness': 100, 'concision': 100,
        'claims': [{'id': 0, 'keys': ['change']}], 'checks': {}})
    assert 'incorrect_numeric_claim' in exact['hard_failures']


def test_decrease_after_amount():
    from .evidence_scoring import extract_numbers
    assert extract_numbers('You spent $50.72 less.')[0]['decrease']


def test_negative_currency_not_confused_with_a_bullet():
    from .evidence_scoring import extract_numbers
    assert extract_numbers('- Income $100.00\nChange -$5.20')[1]['value'] == -5.2


def test_extraction_failure_preserves_other_scores_and_is_separate():
    from .evidence_scoring import assess
    result = assess('$100 cash; $100 still available.', {'expected': {'cash': 100}},
        {'directness': 90, 'concision': 80, 'claims': [{'id': 0, 'keys': ['cash']}], 'checks': {}})
    assert result['scores']['directness'] == .9
    assert result['scores']['concision'] == .8
    assert result['evaluator_errors'] == ['missing_span_classification']
    assert result['valid'] is False


def test_optional_incorrect_number_and_unsupported_semantics_fail():
    from .evidence_scoring import assess
    result = assess('$100 cash and $51 income.',
        {'expected': {'cash': 100}, 'references': {'income': 50},
         'checks': {'no_peer_claim': 'Do not invent peer data'}},
        {'directness': 100, 'concision': 100, 'claims': [
            {'id': 0, 'keys': ['cash']}, {'id': 1, 'keys': ['income']}],
         'checks': {'no_peer_claim': {'passed': False, 'reason': 'unsupported peer claim'}}})
    assert result['scores']['accuracy'] == .5
    assert 'semantic:no_peer_claim' in result['hard_failures']


def test_wrong_scope_same_number_not_automatically_accepted():
    from .evidence_scoring import assess
    result = assess('$100 income.', {'expected': {'cash': 100}},
        {'directness': 90, 'concision': 100, 'claims': [{'id': 0, 'keys': []}], 'checks': {}})
    assert result['scores']['accuracy'] == 0
    assert result['hard_failures']


def test_paragraph_penalty_and_missing_semantic_check():
    from .evidence_scoring import assess
    answer = ' '.join(['word']*180)
    result = assess(answer, {'expected': {}, 'checks': {'grounded': 'No invented facts'}},
        {'directness': 100, 'concision': 100, 'claims': [], 'checks': {}})
    assert result['scores']['concision'] <= 1/3
    assert result['evaluator_errors']


@pytest.mark.parametrize('answer', ['$2,026', 'income 2026', 'one hundred dollars'])
def test_financial_numbers_not_discarded_as_dates(answer):
    from .evidence_scoring import extract_numbers
    assert extract_numbers(answer)
