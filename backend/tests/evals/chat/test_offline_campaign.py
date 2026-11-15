import json
import pytest
from .offline_control import Ledger, InvalidTransition


def inputs():
    return {'split':'development','scenarios':[{'id':name,'evaluation_version':'spans-v2',
        'fixture':{'metrics':{}},'turns':[{'question':str(i),'expected':{}} for i in range(3)]}
        for name in ['a','b']]}


def test_rounds_cover_whole_set_and_stop_at_three(tmp_path):
    from .offline_campaign import Campaign
    prior=tmp_path/'prior.sqlite'
    with Ledger(prior) as l:
        l.add_question('old',{})
        l.start_round('old')
        l.reserve('old','paid',100)
        l.settle('paid',60,{})
    p=tmp_path/'new'
    Campaign.create(p,inputs(),{},prior)
    seen=[]
    def execute(s,setup,t,q,prefix):
        seen.append(q)
        return {'scores':dict(accuracy=1.,directness=.8,concision=1.,cost=1.,latency=1.,tools=1.),
                'hard_failures':[],'turns':[{'question':'q','answer':'a'}]}
    with Campaign(p,executor=execute) as c:
        assert c.ledger.campaign_summary()['prior_microusd']==60
        for n in range(3):
            c.run_round(None)
            if n<2: c.update({},'No-op diagnostic',['a/1'])
        assert seen==['a','b']*3
        with pytest.raises(InvalidTransition): c.run_round(None)
        with pytest.raises(InvalidTransition): c.update({},'extra',['a/1'])


def test_converges_only_when_every_case_passes(tmp_path):
    from .offline_campaign import Campaign
    prior=tmp_path/'prior'
    with Ledger(prior): pass
    p=tmp_path/'new'
    Campaign.create(p,inputs(),{},prior)
    def execute(*args):
        return {'scores':dict(accuracy=1.,directness=1.,concision=1.,cost=1.,latency=1.,tools=1.),
                'hard_failures':[],'turns':[{'question':'q','answer':'a'}]}
    with Campaign(p,executor=execute) as c:
        assert c.run_round(None)['converged']
        with pytest.raises(InvalidTransition): c.update({},'extra',['a/1'])


def test_pending_prior_call_prevents_new_campaign(tmp_path):
    from .offline_campaign import Campaign
    prior=tmp_path/'prior'
    with Ledger(prior) as l:
        l.add_question('old',{})
        l.start_round('old')
        l.reserve('old','pending',100)
    with pytest.raises(ValueError): Campaign.create(tmp_path/'new',inputs(),{},prior)
