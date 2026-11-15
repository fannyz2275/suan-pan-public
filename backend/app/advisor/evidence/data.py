"""Owned database rows become aggregate evidence locally, never raw model context."""
import calendar
import hashlib
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from app.engine.recurring.normalize import normalize_description
from app.engine.transfers import reciprocal_identity
from .contributors import decimal, money
from .pipeline import FixtureAdapter


def month_scope(month=None):
    current = date.fromisoformat(month + '-01') if month else date.today().replace(day=1) - timedelta(days=1)
    current = current.replace(day=1)
    previous = (current - timedelta(days=1)).replace(day=1)
    end = current.replace(day=calendar.monthrange(current.year, current.month)[1])
    if end >= date.today():
        raise ValueError('Select a completed calendar month')
    return {'month':current.strftime('%Y-%m'), 'current_start':current.isoformat(), 'end':end.isoformat(),
            'previous_start':previous.isoformat(), 'previous_end':(current - timedelta(days=1)).isoformat(),
            'current_period':current.strftime('%B').lower(), 'previous_period':previous.strftime('%B').lower()}


def fetch_owned(db, table, uid, *, date_column=None, start=None, end=None):
    rows = []
    for offset in range(0, 100000, 1000):
        q = db.table(table).select('*').eq('user_id', uid).order('id')
        if date_column:
            q = q.gte(date_column, start).lte(date_column, end)
        batch = q.range(offset, offset + 999).execute().data or []
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
    raise ValueError('Evidence exceeds safe pagination limit')


def fixture_from_rows(scope, accounts, transactions, investments, history, snapshots, holdings):
    owned = {a['id'] for a in accounts if a.get('is_active', True)}
    tx = [r for r in transactions if r.get('account_id') in owned]
    metrics = {}
    def alias(row):
        normalized = normalize_description(row.get('description') or '')
        return 'Source_' + hashlib.sha256(normalized.encode()).hexdigest()[:10]
    def transfer(row):
        return row.get('category') == 'transfer' or row.get('transfer_status') in {'auto_paired','user_confirmed_internal','external'}
    for prefix, start, end in [(scope['previous_period'],scope['previous_start'],scope['previous_end']),
                               (scope['current_period'],scope['current_start'],scope['end'])]:
        rows = [r for r in tx if start <= r['date'][:10] <= end]
        eligible = [r for r in rows if not transfer(r)]
        inc = [r for r in eligible if r.get('category') == 'income' and decimal(r['amount']) > 0]
        expense = [r for r in eligible if r.get('category') != 'income']
        credits = [r for r in expense if decimal(r['amount']) > 0]
        total = lambda items: sum((decimal(r['amount']) for r in items), Decimal(0))
        income, net = total(inc), -total(expense)
        values = {'income':income, 'net_spending':net, 'gross_purchases':-total([r for r in expense if decimal(r['amount']) < 0]),
                  'money_kept':income-net, 'savings_rate':(income-net)/income*100 if income > 0 else None,
                  'refund_candidate_amount':total(credits), 'refund_candidate_count':len(credits),
                  'income_source_count':len({alias(r) for r in inc})}
        for group, selected, keyfn, sign in [('category',expense,lambda r:r.get('category') or 'other',-1),
                                            ('merchant',expense,alias,-1),('income_source',inc,alias,1),('refund_source',credits,alias,1)]:
            groups = defaultdict(Decimal)
            for row in selected: groups[keyfn(row)] += decimal(row['amount']) * sign
            values.update({group + '_' + key:v for key,v in groups.items()})
        ir = [r for r in investments if r.get('account_id') in owned and start <= r['date'][:10] <= end]
        for kind in ('transfer_in','transfer_out','dividend','interest','fee','reinvest'):
            values['investment_' + kind] = sum((decimal(r['amount']) if kind in {'dividend','interest'} else abs(decimal(r['amount']))
                for r in ir if r['type'] == kind), Decimal(0))
        values['investment_distributions'] = values['investment_dividend'] + values['investment_interest']
        values['investment_net_contributions'] = values['investment_transfer_in'] - values['investment_transfer_out']
        tr = [r for r in rows if transfer(r)]
        values.update(transfer_in=sum((max(decimal(r['amount']),0) for r in tr),Decimal(0)),
                      transfer_out=sum((max(-decimal(r['amount']),0) for r in tr),Decimal(0)), transfer_row_count=len(tr))
        groups, unresolved = defaultdict(list), []
        values.update(confirmed_pairs=0, confirmed_internal_moved_once=Decimal(0), external_in=Decimal(0), external_out=Decimal(0))
        for row in tr:
            if row.get('transfer_status') == 'external':
                values['external_in'] += max(decimal(row['amount']),0)
                values['external_out'] += max(-decimal(row['amount']),0)
            elif row.get('transfer_group_id'): groups[row['transfer_group_id']].append(row)
            else: unresolved.append(row)
        for pair in groups.values():
            if (len(pair) == 2 and pair[0]['account_id'] != pair[1]['account_id'] and total(pair) == 0
                and min(decimal(r['amount']) for r in pair) < 0
                and (all(r.get('transfer_status') == 'user_confirmed_internal' for r in pair)
                     or reciprocal_identity(*pair))):
                values['confirmed_pairs'] += 1
                values['confirmed_internal_moved_once'] += abs(decimal(pair[0]['amount']))
            else: unresolved.extend(pair)
        values.update(unresolved_rows=len(unresolved), unresolved_transfer_rows=len(unresolved),
                      unresolved_gross_amount=sum((abs(decimal(r['amount'])) for r in unresolved),Decimal(0)))
        metrics.update({prefix + '_' + k:money(v) if v is not None else None for k,v in values.items()})
    previous, current = scope['previous_period'], scope['current_period']
    groups = ('category_', 'merchant_', 'income_source_', 'refund_source_')
    suffixes = {k[len(p)+1:] for k in metrics for p in (previous,current) if k.startswith(p+'_') and k[len(p)+1:].startswith(groups)}
    suffixes.discard('income_source_count')
    for suffix in suffixes:
        a, b = previous+'_'+suffix, current+'_'+suffix
        metrics.setdefault(a, '0.00'); metrics.setdefault(b, '0.00')
        metrics['change_'+suffix] = money(decimal(metrics[b])-decimal(metrics[a]))
    for suffix in ('income','net_spending','money_kept'):
        metrics[suffix+'_change'] = money(decimal(metrics[current+'_'+suffix])-decimal(metrics[previous+'_'+suffix]))
    account_types = {a['id']:a.get('type') for a in accounts}
    def balance(row):
        value = decimal(row['balance'])
        return -abs(value) if account_types.get(row['account_id']) == 'debt' else value
    balances = [{r['account_id']:balance(r) for r in history if r.get('account_id') in owned and r['as_of'][:10] == day}
                for day in (scope['previous_end'], scope['end'])]
    aligned = bool(owned) and all(set(b) == owned for b in balances)
    if aligned:
        metrics[previous+'_net_worth'], metrics[current+'_net_worth'] = [money(sum(b.values())) for b in balances]
        metrics['net_worth_change'] = money(sum(balances[1].values()) - sum(balances[0].values()))
    selected = {s['id']:s for s in snapshots if s.get('account_id') in owned and not s.get('superseded_at') and s['snapshot_date'] == scope['end']}
    positions = defaultdict(Decimal)
    selected_holdings = [h for h in holdings if h['snapshot_id'] in selected]
    for index, h in enumerate(selected_holdings):
        positions[h.get('ticker') or f'unknown_{index}'] += decimal(h['market_value'])
    # Current portfolio storage cash_value denotes explicitly outside-holdings cash.
    outside = sum((decimal(s.get('cash_value') or 0) for s in selected.values()), Decimal(0))
    hv = sum(positions.values(), Decimal(0)); pv = hv + outside
    if selected_holdings:
        metrics.update({current+'_'+k:money(v) for k,v in {'holdings_count':len(positions), 'holdings_value':hv,
            'outside_cash':outside, 'portfolio_value':pv}.items()})
        if pv > 0:
            metrics[current+'_largest_holding_percent'] = money(max(positions.values())/pv*100)
            metrics[current+'_top_five_holdings_percent'] = money(sum(sorted(positions.values(),reverse=True)[:5])/pv*100)
    investment_scope = {a['id'] for a in accounts if a['id'] in owned and a.get('type') in {'brokerage','retirement'}}
    snapshot_accounts = [s['account_id'] for s in selected.values()]
    full_portfolio = bool(investment_scope) and set(snapshot_accounts) == investment_scope and len(snapshot_accounts) == len(investment_scope)
    basis = full_portfolio and bool(selected_holdings) and all(h.get('cost_basis') is not None for h in selected_holdings)
    if basis: metrics[current+'_unrealized_gain'] = money(hv-sum(decimal(h['cost_basis']) for h in selected_holdings))
    metrics['observed_month_count'] = len({r['date'][:7] for r in tx})
    return {'metrics':metrics, 'current_period':current, 'previous_period':previous, 'scope':scope,
            'availability':{'aligned_wealth':aligned,'complete_cost_basis':basis,'complete_portfolio':full_portfolio,'period_security_returns':False,
                            'peer_benchmark':False,'verified_refund_data':False},
            'limitations':['Stored rows only, not statement-certified completeness.', 'Merchant identity is heuristic and anonymized.',
                          'Bank/card and investment scopes may overlap; never add their gross flows.',
                          'Legacy amount-only pairs without reciprocal evidence remain unresolved.']}


class LiveAdapter(FixtureAdapter):
    def __init__(self, fixture, db, uid):
        super().__init__(fixture)
        self.db, self.uid = db, uid

    def with_month(self, month):
        return live_adapter(self.db,self.uid,month)


def live_adapter(db, uid, month=None):
    scope = month_scope(month)
    def dated(table, column):
        return fetch_owned(db,table,uid,date_column=column,start=scope['previous_start'],end=scope['end'])
    accounts = fetch_owned(db,'accounts',uid)
    snapshots = dated('portfolio_snapshots','snapshot_date')
    holdings = []
    for s in snapshots:
        if s.get('superseded_at') or s['snapshot_date'] != scope['end']: continue
        for offset in range(0,100000,1000):
            batch = db.table('snapshot_holdings').select('*').eq('snapshot_id',s['id']).order('id').range(offset,offset+999).execute().data or []
            holdings.extend(batch)
            if len(batch) < 1000: break
        else: raise ValueError('Holdings exceed safe pagination limit')
    fixture = fixture_from_rows(scope, accounts, dated('transactions','date'), dated('investment_transactions','date'),
        dated('account_balance_history','as_of'), snapshots, holdings)
    return LiveAdapter(fixture,db,uid)
