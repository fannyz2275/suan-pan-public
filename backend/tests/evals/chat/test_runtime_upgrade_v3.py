import json
from pathlib import Path
import pytest
from tests.evals.chat.offline_control import Ledger, InvalidTransition
from tests.evals.chat.offline_campaign_v3 import CampaignV3, upgrade_runtime


def test_runtime_change_requires_archived_settled_round(tmp_path):
    root = Path(__file__).parents[3]
    files = list((root/'app/advisor/evidence').glob('*.py')) + [Path(__file__).with_name(n) for n in (
        'offline_campaign_v3.py','offline_conversation_v3.py','evidence_scoring_v3.py','openrouter_transport.py','offline_control.py')]
    snapshot = tmp_path/'snapshot.json'
    snapshot.write_text(json.dumps({str(p.relative_to(root)):p.read_text() for p in files}))
    prior = tmp_path/'prior.sqlite'
    with Ledger(prior) as ledger: ledger.configure_campaign(1_000_000,406462,'prior')
    setup = json.loads(Path('tests/evals/chat/offline-setup-v3.json').read_text())
    path = tmp_path/'run'
    CampaignV3.create(path,{'split':'development','scenarios':[{'id':'a','turns':[{'question':'q'}]}]},setup,prior)
    with pytest.raises(InvalidTransition): upgrade_runtime(path,snapshot,'too early')
    with CampaignV3(path,executor=lambda *args:dict(scores=None,score=None,scorable=False,passed=False,hard_failures=[],
                                                   evaluator_errors=['bad'],turns=[{'question':'q','answer':'a'}])) as c:
        c.run_round(None)
    upgrade_runtime(path,snapshot,'record an explicit candidate boundary')
    with pytest.raises(InvalidTransition): upgrade_runtime(path,snapshot,'duplicate')
    with CampaignV3(path) as c:
        assert c.report()['budget']['spent_microusd'] == 406462
        assert len(c.manifest['runtime_updates']) == 1
