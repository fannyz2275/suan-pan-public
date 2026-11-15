"""Pure, read-only evidence calculations. Never infer missing ownership or prices."""
from collections import defaultdict
from decimal import Decimal


def amount(value):
    result=Decimal(str(value))
    if not result.is_finite(): raise ValueError('Nonfinite amount')
    return result


def money(value): return float(amount(value).quantize(Decimal('.01')))


def holdings_summary(holdings, outside_cash=0):
    positions=defaultdict(Decimal)
    for index,h in enumerate(holdings):
        key=h.get('ticker','').strip().upper() or ('unknown',index)
        positions[key]+=amount(h['market_value'])
    values=list(positions.values())
    total=sum(values,Decimal(0))
    result={'holdings_count':len(values),'holdings_value':money(total),
            'outside_cash':money(outside_cash),'portfolio_value':money(total+amount(outside_cash)),
            'unrealized_gain_available':bool(holdings) and all(h.get('cost_basis') is not None for h in holdings)}
    if total>0:
        result['largest_holding_percent']=money(max(values)/total*100)
        result['top_five_holdings_percent']=money(sum(sorted(values,reverse=True)[:5])/total*100)
    if result['unrealized_gain_available']:
        result['lifetime_unrealized_gain']=money(total-sum((amount(h['cost_basis']) for h in holdings),Decimal(0)))
    return result


def transfer_summary(rows, owned):
    groups=defaultdict(list)
    unresolved=[]
    external_in=external_out=Decimal(0)
    for row in rows:
        if row['account_id'] not in owned: raise ValueError('Unexpected account scope')
        if row.get('transfer_status')=='external':
            v=amount(row['amount'])
            external_in+=max(v,0)
            external_out+=max(-v,0)
        elif row.get('transfer_group_id'):
            groups[row['transfer_group_id']].append(row)
        else: unresolved.append(row)
    moved=Decimal(0)
    pairs=0
    for group in groups.values():
        values=[amount(r['amount']) for r in group]
        if (len(group)==2 and len({r['account_id'] for r in group})==2 and
            all(r.get('transfer_status') in {'auto_paired','user_confirmed_internal'} for r in group) and
            sum(values)==0 and min(values)<0<max(values)):
            moved+=max(values)
            pairs+=1
        else: unresolved.extend(group)
    return {'confirmed_internal_moved_once':money(moved),'confirmed_pairs':pairs,
            'external_in':money(external_in),'external_out':money(external_out),
            'unresolved_rows':len(unresolved),'unresolved_gross_amount':money(sum((abs(amount(r['amount'])) for r in unresolved),Decimal(0)))}


def aligned_wealth(history, owned, start, end):
    by_date={}
    for boundary in (start,end):
        rows={}
        for row in sorted(history,key=lambda r:r['as_of']):
            if row['as_of'][:10]==boundary and row['account_id'] in owned:
                rows[row['account_id']]=amount(row['balance'])
        by_date[boundary]=rows
    available=bool(owned) and all(set(rows)==owned for rows in by_date.values())
    result={'available':available,'opening_accounts':len(by_date[start]),'closing_accounts':len(by_date[end]),'required_accounts':len(owned)}
    if available:
        opening=sum(by_date[start].values())
        closing=sum(by_date[end].values())
        result.update(opening=money(opening),closing=money(closing),change=money(closing-opening))
    return result


def refund_summary(rows):
    credits=[r for r in rows if r.get('category') not in {'income','transfer'} and amount(r['amount'])>0
             and r.get('transfer_status') not in {'auto_paired','user_confirmed_internal','external'}]
    verified=[r for r in credits if r.get('refund_verified') is True]
    return {'candidate_count':len(credits),'candidate_amount':money(sum((amount(r['amount']) for r in credits),Decimal(0))),
            'verified_count':len(verified),'verified_amount':money(sum((amount(r['amount']) for r in verified),Decimal(0)))}
