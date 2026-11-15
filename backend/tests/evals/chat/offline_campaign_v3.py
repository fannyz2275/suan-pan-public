"""Versioned campaign; never rewrite an earlier run or reset its spending."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
from .offline_campaign import prior_receipt
from .offline_control import Ledger, InvalidTransition, PendingCall, WEIGHTS
from .offline_workflow import save, digest
from .offline_conversation import validate_setup
from .offline_conversation_v3 import run_conversation


def runtime_hash():
    root = Path(__file__).parents[3]
    paths = list((root/'app/advisor/evidence').glob('*.py')) + [Path(__file__).with_name(n) for n in (
        'offline_campaign_v3.py','offline_conversation_v3.py','evidence_scoring_v3.py','openrouter_transport.py','offline_control.py')]
    return digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def upgrade_runtime(path, snapshot, reason):
    """Explicit candidate-code transition, only between rounds, preserving scorer and budget."""
    if not reason: raise ValueError('Runtime change needs a reason')
    sources = json.loads(snapshot.read_text())
    with (path/'workflow.lock').open('a') as lock, Ledger(path/'ledger.sqlite') as ledger:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest = json.loads(ledger.db.execute('SELECT payload FROM v3_manifest').fetchone()[0])
        source_hash = digest({k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()})
        if source_hash != manifest['runtime_hash']:
            raise InvalidTransition('Archive does not match the previous frozen runtime')
        for name in ('evidence_scoring_v3.py','offline_control.py','openrouter_transport.py'):
            key = 'tests/evals/chat/' + name
            if sources.get(key) != Path(__file__).with_name(name).read_text():
                raise InvalidTransition('Scoring and accounting cannot change between rounds')
        states = [ledger.summary(s['id']) for s in manifest['scenarios']]
        n = len(states[0]['rounds'])
        if n not in (1,2) or any(len(s['rounds']) != n or s['active_round'] is not None or s['pending_call_ids'] for s in states):
            raise InvalidTransition('Runtime updates require a complete, settled round before the final round')
        if any(u['after_round'] == n for u in manifest.get('runtime_updates',[])):
            raise InvalidTransition('Runtime update already recorded for this boundary')
        if prior_receipt(Path(manifest['prior']['path'])) != manifest['prior']:
            raise InvalidTransition('Prior receipt changed')
        manifest.setdefault('initial_runtime_hash',manifest['runtime_hash'])
        manifest.setdefault('runtime_updates',[]).append({'after_round':n,'before':manifest['runtime_hash'],
            'after':runtime_hash(),'source_snapshot':str(snapshot),'reason':reason})
        manifest['runtime_hash'] = runtime_hash()
        ledger.db.execute('UPDATE v3_manifest SET payload=?',(json.dumps(manifest),))
        save(path/'manifest.json',manifest)


class CampaignV3:
    @staticmethod
    def create(path, dataset, setup, prior):
        receipt = prior_receipt(prior)
        if dataset.get('split') != 'development' or not dataset.get('scenarios'):
            raise ValueError('Explicit development scenarios required')
        ids = [s['id'] for s in dataset['scenarios']]
        if len(set(ids)) != len(ids): raise ValueError('Duplicate scenario IDs')
        setup = validate_setup(setup)
        manifest = {'scenarios':dataset['scenarios'],'baseline':setup,'prior':receipt,
                    'runtime_hash':runtime_hash(),'scoring_version':'references-v3','weights':WEIGHTS}
        path.mkdir(parents=True,exist_ok=False)
        with Ledger(path/'ledger.sqlite') as ledger:
            ledger.configure_campaign(1_000_000,receipt['spent_microusd'],digest(receipt))
            ledger.db.execute('CREATE TABLE v3_manifest(payload TEXT NOT NULL)')
            ledger.db.execute('INSERT INTO v3_manifest VALUES (?)',(json.dumps(manifest),))
            for scenario in dataset['scenarios']: ledger.add_question(scenario['id'],setup)
        save(path/'manifest.json',manifest)

    def __init__(self,path,executor=None):
        self.path = path
        self.lock = (path/'workflow.lock').open('a')
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.ledger = Ledger(path/'ledger.sqlite')
        self.manifest = json.loads(self.ledger.db.execute('SELECT payload FROM v3_manifest').fetchone()[0])
        if self.manifest['runtime_hash'] != runtime_hash() or prior_receipt(Path(self.manifest['prior']['path'])) != self.manifest['prior']:
            self.__exit__(None,None,None)
            raise InvalidTransition('Frozen runtime or prior receipt changed')
        self.executor = executor or run_conversation

    def __enter__(self): return self
    def __exit__(self,*args):
        self.ledger.__exit__(*args)
        self.lock.close()

    def report(self):
        questions = []
        for scenario in self.manifest['scenarios']:
            state = self.ledger.summary(scenario['id'])
            # Legacy ledger numeric bookkeeping is not an evaluation score when unscorable.
            questions.append({'question':scenario['id'],'rounds':[{'number':r['number'],'setup':r['setup'],**r['details']} for r in state['rounds']],
                              'active_round':state['active_round'],'updates':state['updates'],'pending_call_ids':state['pending_call_ids']})
        complete = min(len(q['rounds']) for q in questions)
        converged = bool(complete and all(len(q['rounds']) == complete and q['rounds'][-1]['passed'] for q in questions))
        budget = self.ledger.campaign_summary()
        report = {'questions':questions,'complete_rounds':complete,'converged':converged,
                  'budget':budget,'scoring_version':'references-v3','judge_calibrated':False,'heldout':False,
                  'stop_reason':budget['stop_reason'] or ('converged' if converged else 'three_round_limit' if complete == 3 else None)}
        save(self.path/'report.json',report)
        save(self.path/'retained-setup.json',questions[0]['rounds'][-1]['setup'] if converged else self.manifest['baseline'])
        if questions[0]['rounds']: save(self.path/'last-tested-setup.json',questions[0]['rounds'][-1]['setup'])
        return report

    def run_round(self, transport):
        report = self.report()
        if report['converged'] or report['complete_rounds'] >= 3:
            raise InvalidTransition('Converged or three rounds completed')
        if any(q['pending_call_ids'] for q in report['questions']): raise PendingCall('Reconcile charges first')
        number = report['complete_rounds'] + 1
        for scenario in self.manifest['scenarios']:
            state = self.ledger.summary(scenario['id'])
            if len(state['rounds']) >= number: continue
            if state['active_round'] is None: self.ledger.start_round(scenario['id'])
            try:
                result = self.executor(scenario,state['setup'],transport,scenario['id'],f"{scenario['id']}/round-{number}")
                result['runtime_hash'] = self.manifest['runtime_hash']
                bookkeeping = result['scores'] or dict.fromkeys(WEIGHTS,0.)
                failures = result['hard_failures'] + (['unscorable_evaluator'] if not result['scorable'] else [])
                self.ledger.finish_round(scenario['id'],bookkeeping,failures,result['turns'],result)
                print(json.dumps({'question':scenario['id'],'round':number,'score':result['score'],
                                  'passed':result['passed'],'failures':result['hard_failures'],'evaluator_errors':result['evaluator_errors']}),flush=True)
            finally: self.report()
        return self.report()

    def update(self,candidate,reason,cases):
        report = self.report(); n = report['complete_rounds']
        if n not in (1,2) or report['converged'] or any(len(q['rounds']) != n or q['active_round'] is not None for q in report['questions']):
            raise InvalidTransition('Only two updates between complete rounds')
        if not reason or not cases: raise ValueError('Require reasons and triggering cases')
        valid = {f"{s['id']}/{i+1}" for s in self.manifest['scenarios'] for i in range(len(s['turns']))}
        if not set(cases) <= valid: raise ValueError('Unknown triggering case')
        candidate = validate_setup(candidate)
        if candidate['tools']:
            raise ValueError('v3 uses frozen production tools, not candidate arithmetic code')
        for q in report['questions']:
            if len(q['updates']) == n:
                if q['updates'][-1]['proposed'] != candidate: raise InvalidTransition('Partial update mismatch')
                continue
            self.ledger.apply_update(q['question'],candidate,reason,cases,json.dumps(candidate),True)
        return self.report()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command',choices=['init','run-round','update','report'])
    for key in ('run-dir','dataset','setup','prior-ledger','env-file','candidate'):
        parser.add_argument('--'+key,type=Path,required=key=='run-dir')
    parser.add_argument('--reason'); parser.add_argument('--cases',nargs='+')
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text())
    if args.command == 'init':
        CampaignV3.create(args.run_dir,read(args.dataset),read(args.setup),args.prior_ledger)
        print('Initialized without paid calls'); return
    with CampaignV3(args.run_dir) as c:
        if args.command == 'run-round':
            from dotenv import dotenv_values
            from .openrouter_transport import OpenRouterTransport
            import os
            key = os.getenv('OPENROUTER_API_KEY') or dotenv_values(args.env_file).get('OPENROUTER_API_KEY')
            c.run_round(OpenRouterTransport(c.ledger,key))
        elif args.command == 'update': c.update(read(args.candidate),args.reason,args.cases)
        report = c.report()
        print(json.dumps({k:report[k] for k in ('complete_rounds','converged','budget','stop_reason')}))


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('Campaign stopped:',type(exc).__name__)
        raise SystemExit(1)
