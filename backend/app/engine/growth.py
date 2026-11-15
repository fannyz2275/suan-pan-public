"""Recorded net-worth changes for a fixed universe of active accounts."""
from datetime import date

from app.engine.snapshot import compute_snapshot


def bucket(account_type):
    if account_type in ('checking', 'savings'):
        return 'cash'
    if account_type in ('brokerage', 'retirement'):
        return 'investments'
    return 'debt' if account_type == 'debt' else 'other'


def compute_growth(accounts, history, snapshots, transactions, start, today):
    types = {a['id']: a['type'] for a in accounts}
    end = today.isoformat()
    history = sorted([r for r in history if r['account_id'] in types and str(r['as_of'])[:10] <= end], key=lambda r: str(r['as_of']))
    first = str(history[0]['as_of'])[:10] if history else end
    start_iso = start.isoformat() if start else first
    days = sorted({start_iso, *[str(r['as_of'])[:10] for r in history if str(r['as_of'])[:10] >= start_iso]})
    series, latest, index = [], {}, 0
    for day in days:
        while index < len(history) and str(history[index]['as_of'])[:10] <= day:
            row = history[index]
            latest[row['account_id']] = float(row['balance'])
            index += 1
        values = dict.fromkeys(('cash', 'investments', 'other', 'debt'), 0.0)
        for aid, value in latest.items():
            key = bucket(types[aid])
            values[key] += -abs(value) if key == 'debt' else value
        complete = bool(types) and len(latest) == len(types)
        series.append({'date': day, 'net_worth': round(sum(values.values()), 2) if complete else None,
                       'covered_accounts': len(latest), 'values': values if complete else None})
    snapshot = compute_snapshot(accounts)
    current = {'cash': snapshot['liquid_assets'], 'investments': snapshot['investment_assets'],
               'other': snapshot['non_current_assets'], 'debt': -snapshot['total_liabilities'], 'net_worth': snapshot['net_worth']}
    baseline = next((p for p in series if p['net_worth'] is not None and p['date'] < end), None)
    changes = {key: round(current[key] - baseline['values'][key], 2) for key in ('cash', 'investments', 'other', 'debt')} if baseline else None
    change = round(current['net_worth'] - baseline['net_worth'], 2) if baseline else None
    # Today's point is the current recorded account snapshot, not a live quote.
    series = [p for p in series if p['date'] < end]
    series.append({'date': end, 'net_worth': current['net_worth'] if accounts else None, 'covered_accounts': len(accounts), 'values': current})
    investment_ids = {aid for aid, kind in types.items() if bucket(kind) == 'investments'}

    def unrealized(as_of):
        latest_snaps = {}
        for snap in sorted(snapshots, key=lambda s: (s['snapshot_date'], s.get('created_at', ''))):
            if snap['account_id'] in investment_ids and snap['snapshot_date'] <= as_of:
                latest_snaps[snap['account_id']] = snap
        holdings = [h for snap in latest_snaps.values() for h in snap.get('snapshot_holdings', [])]
        known = [h for h in holdings if h.get('cost_basis') is not None and h.get('market_value') is not None]
        complete = bool(investment_ids) and len(latest_snaps) == len(investment_ids) and len(known) == len(holdings)
        for snap in latest_snaps.values():
            if snap.get('total_value') is not None:
                holding_total = sum(float(h.get('market_value') or 0) for h in snap.get('snapshot_holdings', []))
                if abs(float(snap['total_value']) - float(snap.get('cash_value') or 0) - holding_total) > 1:
                    complete = False
        dates = sorted(s['snapshot_date'] for s in latest_snaps.values())
        return {'value': round(sum(float(h['market_value']) - float(h['cost_basis']) for h in known), 2) if complete else None,
                'known_holdings': len(known), 'total_holdings': len(holdings),
                'covered_accounts': len(latest_snaps), 'total_accounts': len(investment_ids),
                'oldest_date': dates[0] if dates else None, 'latest_date': dates[-1] if dates else None}

    current_unrealized = unrealized(end)
    prior_unrealized = unrealized(baseline['date']) if baseline else None
    flows = [t for t in transactions if t['account_id'] in investment_ids and baseline and baseline['date'] < t['date'] <= end and t['type'] in ('transfer_in', 'transfer_out')]
    net = sum(abs(float(t['amount'])) * (1 if t['type'] == 'transfer_in' else -1) for t in flows)
    return {'requested_start': start_iso, 'baseline_date': baseline['date'] if baseline else None,
            'as_of': end, 'account_count': len(accounts), 'current': current,
            'change': change, 'percent_change': round(change / baseline['net_worth'] * 100, 2) if baseline and baseline['net_worth'] > 0 else None,
            'changes': changes, 'series': series,
            'balance_dates': [{'name': a.get('name', a['id']), 'date': a.get('balance_updated_at') or a.get('created_at')} for a in accounts],
            'investments': {'net_contributions': round(net, 2) if flows else None, 'flow_count': len(flows),
                'unrealized': current_unrealized, 'prior_unrealized': prior_unrealized,
                'unrealized_change': round(current_unrealized['value'] - prior_unrealized['value'], 2) if prior_unrealized and prior_unrealized['value'] is not None and current_unrealized['value'] is not None else None}}


def load_growth(db, user_id, start: date | None, today: date):
    def pages(query):
        rows = []
        offset = 0
        while True:
            page = query.range(offset, offset + 499).execute().data or []
            rows.extend(page)
            if len(page) < 500:
                return rows
            offset += 500

    accounts = pages(db.table('accounts').select('*').eq('user_id', user_id).eq('is_active', True).order('id'))
    history = pages(db.table('account_balance_history').select('*').eq('user_id', user_id).order('as_of').order('id'))
    snapshots = pages(db.table('portfolio_snapshots').select('*,snapshot_holdings(*)').eq('user_id', user_id).is_('superseded_at', None).order('snapshot_date').order('id'))
    transactions = pages(db.table('investment_transactions').select('account_id,date,type,amount,id').eq('user_id', user_id).in_('type', ['transfer_in', 'transfer_out']).order('date').order('id'))
    return compute_growth(accounts, history, snapshots, transactions, start, today)
