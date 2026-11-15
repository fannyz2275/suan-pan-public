"""Whole-set rounds with a cumulative, carried-forward USD 1 budget.

An explicitly authorized new campaign retains the prior pilot unchanged. It is a
new scorer version, not another allowance. No production configuration is promoted.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .offline_control import Ledger, InvalidTransition, PendingCall, passes
from .offline_conversation import run_conversation, validate_scenario, validate_setup
from .offline_workflow import save, digest


def runtime_hash():
    return digest({name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
        for name in ['offline_campaign.py','offline_control.py','offline_conversation.py',
                     'openrouter_transport.py','evidence_scoring.py']})


def prior_receipt(path):
    path=path.resolve()
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        if db.execute('SELECT count(*) FROM calls WHERE actual IS NULL').fetchone()[0]:
            raise ValueError('Prior pending charges must be reconciled first')
        spent=db.execute('SELECT COALESCE(SUM(actual),0) FROM calls').fetchone()[0]
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='campaign_budget'").fetchone():
            row=db.execute('SELECT prior FROM campaign_budget WHERE id=1').fetchone()
            spent+=row[0] if row else 0
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'spent_microusd':spent}


class Campaign:
    @staticmethod
    def create(path,dataset,setup,prior):
        if dataset.get('split')!='development':
            raise ValueError('This optimizer only accepts development data')
        scenarios=[validate_scenario(s) for s in dataset['scenarios']]
        if not scenarios or len({s['id'] for s in scenarios})!=len(scenarios) or any(
            s.get('evaluation_version')!='spans-v2' or not 3<=len(s['turns'])<=5 for s in scenarios):
            raise ValueError('Require unique spans-v2 scripted conversations')
        setup=validate_setup(setup)
        receipt=prior_receipt(prior)
        manifest={'scenarios':scenarios,'baseline':setup,'prior':receipt,'runtime_hash':runtime_hash(),
                  'split':'development','judge_calibrated':False,'cap_microusd':1_000_000}
        path.mkdir(parents=True,exist_ok=False)
        with Ledger(path/'ledger.sqlite') as ledger:
            ledger.configure_campaign(1_000_000,receipt['spent_microusd'],digest(receipt))
            ledger.db.execute('CREATE TABLE artifacts(name TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            ledger.db.execute('INSERT INTO artifacts VALUES (?,?)',('manifest',json.dumps(manifest)))
            ledger.db.execute('INSERT INTO artifacts VALUES (?,?)',('tool_oracles',json.dumps({t['name']:t['tests'] for t in setup['tools']})))
            for s in scenarios: ledger.add_question(s['id'],setup)
        save(path/'manifest.json',manifest)

    def __init__(self,path,executor=None):
        self.path=path
        self.lock=(path/'workflow.lock').open('a')
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.ledger=Ledger(path/'ledger.sqlite')
        self.manifest=json.loads(self.ledger.db.execute("SELECT payload FROM artifacts WHERE name='manifest'").fetchone()[0])
        if self.manifest['runtime_hash']!=runtime_hash() or prior_receipt(Path(self.manifest['prior']['path']))!=self.manifest['prior']:
            self.__exit__(None,None,None)
            raise InvalidTransition('Frozen runtime or prior ledger changed')
        self.executor=executor or run_conversation

    def __enter__(self): return self

    def __exit__(self,*args):
        self.ledger.__exit__(*args)
        self.lock.close()

    def report(self):
        questions=[self.ledger.summary(s['id']) for s in self.manifest['scenarios']]
        complete_rounds=min(len(q['rounds']) for q in questions)
        same_round=all(len(q['rounds'])==complete_rounds and q['active_round'] is None for q in questions)
        converged=bool(complete_rounds and same_round and all(q['rounds'][-1]['passed'] for q in questions))
        budget=self.ledger.campaign_summary()
        result={'questions':questions,'complete_rounds':complete_rounds,'converged':converged and not budget['stop_reason'],
                'budget':budget,'judge_calibrated':False,'promotion':'manual only; human calibration and unseen holdout remain required',
                'runtime_hash':self.manifest['runtime_hash'],'dataset_hash':digest(self.manifest['scenarios'])}
        save(self.path/'report.json',result)
        # Only a fully passing whole-set candidate qualifies as retained.
        retained=questions[0]['rounds'][-1]['setup'] if result['converged'] else self.manifest['baseline']
        save(self.path/'retained-setup.json',retained)
        if questions[0]['rounds']: save(self.path/'last-tested-setup.json',questions[0]['rounds'][-1]['setup'])
        return result

    def run_round(self,transport):
        report=self.report()
        if report['converged'] or report['complete_rounds']>=3:
            raise InvalidTransition('Converged or three rounds completed')
        if any(q['pending_call_ids'] for q in report['questions']):
            raise PendingCall('Reconcile unknown charges before resuming')
        number=report['complete_rounds']+1
        for s in self.manifest['scenarios']:
            q=self.ledger.summary(s['id'])
            if len(q['rounds'])>=number: continue
            if q['active_round'] is None: self.ledger.start_round(s['id'])
            try:
                result=self.executor(s,q['setup'],transport,s['id'],f"{s['id']}/round-{number}")
                self.ledger.finish_round(s['id'],result['scores'],result['hard_failures'],result['turns'],result)
                print(json.dumps({'question':s['id'],'round':number,'scores':result['scores'],
                                  'failures':result['hard_failures']}),flush=True)
            finally:
                self.report()
        return self.report()

    def update(self,candidate,reason,cases):
        report=self.report()
        n=report['complete_rounds']
        if n not in (1,2) or report['converged'] or any(len(q['rounds'])!=n or q['active_round'] is not None for q in report['questions']):
            raise InvalidTransition('Update only between full, non-converged rounds')
        allowed={f"{s['id']}/{i+1}" for s in self.manifest['scenarios'] for i in range(len(s['turns']))}
        if not reason or not cases or not set(cases)<=allowed:
            raise ValueError('Require real triggering cases')
        candidate=validate_setup(candidate)
        registry=json.loads(self.ledger.db.execute("SELECT payload FROM artifacts WHERE name='tool_oracles'").fetchone()[0])
        for tool in candidate['tools']:
            tests=registry.get(tool['name'],[])+tool['tests']
            tool['tests']=list({json.dumps(t,sort_keys=True):t for t in tests}.values())
            registry[tool['name']]=tool['tests']
        validate_setup(candidate)
        for q in report['questions']:
            if len(q['updates'])==n:
                if q['updates'][-1]['proposed']!=candidate:
                    raise InvalidTransition('Partially applied update differs')
                continue
            self.ledger.apply_update(q['question'],candidate,reason,cases,
                json.dumps({'before':q['setup'],'after':candidate},sort_keys=True),True,registry)
        return self.report()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['init','run-round','update','report'])
    p.add_argument('--run-dir',type=Path,required=True)
    for arg in ['dataset','setup','prior-ledger','candidate','env-file']: p.add_argument('--'+arg,type=Path)
    p.add_argument('--reason')
    p.add_argument('--cases',nargs='+')
    a=p.parse_args()
    read=lambda path:json.loads(path.read_text())
    if a.command=='init':
        Campaign.create(a.run_dir,read(a.dataset),read(a.setup),a.prior_ledger)
        print('Campaign initialized; no paid calls.')
        return
    with Campaign(a.run_dir) as c:
        if a.command=='run-round':
            from dotenv import dotenv_values
            from .openrouter_transport import OpenRouterTransport
            key=os.environ.get('OPENROUTER_API_KEY') or (dotenv_values(a.env_file).get('OPENROUTER_API_KEY') if a.env_file else None)
            c.run_round(OpenRouterTransport(c.ledger,key))
        elif a.command=='update': c.update(read(a.candidate),a.reason,a.cases)
        r=c.report()
        print(json.dumps({'rounds':r['complete_rounds'],'converged':r['converged'],'budget':r['budget']}))


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('Campaign stopped:',type(exc).__name__)
        raise SystemExit(1)
