import pytest
from tests.evals.chat.offline_control import Ledger, InvalidTransition
from tests.evals.chat.offline_campaign_v3 import CampaignV3
from pathlib import Path
import json


def test_three_rounds_unscorable_and_carryover(tmp_path):
    prior = tmp_path/'prior.sqlite'
    with Ledger(prior) as ledger:
        ledger.configure_campaign(1_000_000,406462,'previous')
    setup = json.loads(Path('tests/evals/chat/offline-setup-v2.json').read_text())
    scenario = {'id':'a','turns':[{'question':'q'}]}
    path = tmp_path/'run'
    CampaignV3.create(path,{'split':'development','scenarios':[scenario]},setup,prior)
    def fake(*args):
        return {'scores':None,'score':None,'scorable':False,'passed':False,'hard_failures':[],
                'evaluator_errors':['invalid_judge'],'turns':[{'question':'q','answer':'a'}]}
    with CampaignV3(path,executor=fake) as c:
        for index in range(3):
            r = c.run_round(None)
            assert r['questions'][0]['rounds'][-1]['score'] is None
            if index < 2: c.update(setup,'Test update',['a/1'])
        assert r['budget']['remaining_microusd'] == 593538
        with pytest.raises(InvalidTransition): c.run_round(None)
        with pytest.raises(InvalidTransition): c.update(setup,'extra',['a/1'])
