import pytest
from app.advisor.evidence.registry import definition, build_evidence
from app.advisor.evidence.contributors import rank_contributors


def test_definitions_are_static_and_unknown_is_rejected():
    assert definition('september_income')['unit'] == 'USD'
    assert definition('august_income')['meaning'] == definition('september_income')['meaning']
    with pytest.raises(ValueError):
        definition('invented_metric')


def test_version_and_null_boundary():
    with pytest.raises(ValueError):
        build_evidence({'september_income': 4}, definition_version='unknown')
    result = build_evidence({'september_income': None})
    assert result['metrics']['september_income']['value'] is None


def test_top_contributors_sorted_and_remainder():
    result = rank_contributors([{'id': 'aw', 'current': '255.00', 'previous': '0'},
                                {'id': 'z', 'current': '285.78', 'previous': '20'}], measure='current', limit=1)
    assert result['rows'][0]['id'] == 'z'
    assert result['remainder'] == '255.00'
    assert result['rows'][0]['change'] == '265.78'


def test_ties_and_zero_baseline():
    rows = [{'id': 'b', 'current': '10', 'previous': '0'}, {'id': 'a', 'current': '10', 'previous': '0'}]
    result = rank_contributors(rows, measure='change', limit=2)
    assert [r['id'] for r in result['rows']] == ['a', 'b']
    assert result['rows'][0]['change_percent'] is None


def test_absolute_change_and_finite():
    result = rank_contributors([{'id':'up','current':10,'previous':0},
                               {'id':'down','current':0,'previous':20}], measure='absolute_change', limit=1)
    assert result['rows'][0]['id'] == 'down'
    with pytest.raises(ValueError):
        rank_contributors([{'id':'bad','current':'NaN','previous':0}])
