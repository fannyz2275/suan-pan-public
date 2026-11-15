import pytest
from app.advisor.pending import readiness, claim_state


def test_partial_import_and_same_version_not_ready():
    pending = {'requirements':['aligned_wealth'], 'data_version':'old', 'status':'waiting'}
    assert not readiness(pending, {'aligned_wealth':True}, 'old')['ready']
    assert not readiness(pending, {'aligned_wealth':False}, 'new')['ready']
    assert readiness(pending, {'aligned_wealth':True}, 'new')['ready']


def test_resume_claim_state_is_idempotent():
    assert claim_state('waiting') == 'run'
    assert claim_state('complete') == 'cached'
    with pytest.raises(ValueError): claim_state('running')


def test_peer_data_does_not_offer_upload():
    pending = {'requirements':['peer_benchmark'], 'data_version':'old', 'status':'waiting'}
    assert not readiness(pending, {}, 'new')['upload_action']
