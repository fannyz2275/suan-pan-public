from unittest.mock import patch

import pytest

from app.imports.sections import detect_sections, suggest_account


def section(start, end, last4):
    return {"institution": "Chase", "type": "checking", "last4": last4,
            "ranges": [[start, end]], "uncertain": False}


def test_separate_account_source_text():
    text = "Chase checking 1234\nDeposit 100\nChase checking 5678\nWithdrawal 50"
    with patch('app.imports.sections._call_gemini', return_value=[section(1, 2, '1234'), section(3, 4, '5678')]):
        result = detect_sections(text)
    assert 'Withdrawal' not in result[0]['text']
    assert 'Deposit' not in result[1]['text']


@pytest.mark.parametrize('rows', [
    [section(1, 2, '1234'), section(2, 3, None)],
    [section(1, 3, '9999')],
])
def test_unsafe_boundaries_fail_closed(rows):
    with patch('app.imports.sections._call_gemini', return_value=rows), pytest.raises(ValueError):
        detect_sections('Chase 1234\nDeposit 100\nWithdrawal 50')


def test_last_four_alone_or_duplicate_matches_are_not_suggested():
    detected = {'institution': 'Chase', 'type': 'checking', 'last4': '1234'}
    account = {'id': 'a', 'name': 'Chase Checking', 'type': 'checking', 'account_number_last4': '1234'}
    assert suggest_account(detected, [account]) == 'a'
    assert suggest_account(detected, [account, {**account, 'id': 'b'}]) == ''
    assert suggest_account(detected, [{**account, 'name': 'Other Bank'}]) == ''
    assert suggest_account(detected, [{**account, 'type': 'savings'}]) == ''


def test_shared_context_and_disclosures_do_not_invalidate_accounts():
    raw = [{'role': 'context', 'ranges': [[1, 1]]}, section(2, 3, '1234'),
           {'role': 'disclosure', 'ranges': [[4, 4]]}]
    with patch('app.imports.sections._call_gemini', return_value=raw):
        result = detect_sections('Chase\nChecking 1234\nDeposit 100\nMember FDIC')
    assert len(result) == 1
    assert 'Chase' in result[0]['text']
    assert 'FDIC' not in result[0]['text']
    assert len(result[0]['document_notices']) == 2


def test_missing_and_uncertain_content_remains_visible_for_review():
    raw = [section(1, 2, '1234'), {**section(3, 3, None), 'uncertain': True}]
    with patch('app.imports.sections._call_gemini', return_value=raw):
        result = detect_sections('Chase 1234\nDeposit 100\nUnknown account\nOther row')
    assert 'error' not in result[0]
    assert result[1]['error_code'] == 'boundaries'
    assert result[2]['error_code'] == 'unassigned_content'


def test_provider_error_is_distinct_and_does_not_leak_details():
    from app.imports.sections import DetectionError
    with patch('app.imports.sections._call_gemini', side_effect=RuntimeError('secret')):
        with pytest.raises(DetectionError) as error:
            detect_sections('Chase 1234')
    assert error.value.code == 'provider_unavailable'
    assert 'secret' not in str(error.value)
