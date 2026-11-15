"""Code-owned task dependencies and required answer facts, before interpretation."""
from .contracts import ToolRequest
from .contributors import decimal, money


TASKS = {
    'general': 'Other questions; choose individual tools.',
    'income_summary': 'Recorded income totals and source ranking for the current period.',
    'income_change': 'Income comparison and contributors to its change, including short follow-ups about those contributors.',
    'wealth_change': 'Total wealth change, attribution or reconciliation. Includes follow-ups asking how much is explained by salary/spending versus investment performance. Not a standalone spending comparison.',
}


def dependencies(task):
    if task.startswith('income_'):
        return [ToolRequest(tool='summary'), ToolRequest(tool='contributors', group='income_source',
                measure='absolute_change' if task == 'income_change' else 'current')]
    if task == 'wealth_change':
        return [ToolRequest(tool='summary'), ToolRequest(tool='wealth'), ToolRequest(tool='investments')]
    return []


def answer_contract(task, adapter, values, rankings):
    blocks, checks = [], {}
    current, previous = adapter.current, adapter.previous
    availability = adapter.context().get('availability', {})
    present = lambda keys: all(values.get(k) is not None for k in keys)
    ref = lambda key: '{{' + key + '}}'

    if task.startswith('income_'):
        keys = [previous+'_income', current+'_income', 'income_change']
        if task == 'income_change' and not present(keys):
            rankings.clear()
            for key in list(values):
                if key.startswith(previous+'_income_source_') or key.startswith('change_income_source_'):
                    values.pop(key)
            return {'task':task, 'reconciled':False, 'required_blocks':[{'text':
                'Income change and its contributors are unavailable without comparable income totals. Import statements for both periods before attributing the change.'}]}
        if task == 'income_summary' and present([keys[1]]):
            blocks.append({'text': f'Recorded income: {current.title()} {ref(keys[1])}. This is recorded income, not independently verified salary.'})
        elif present(keys):
            before, after, change = (decimal(values[k]) for k in keys)
            if money(after-before) != money(change):
                raise ValueError('Income reconciliation failed')
            blocks.append({'text': f'Recorded income: {previous.title()} {ref(keys[0])}; {current.title()} {ref(keys[1])}; change {ref(keys[2])}. This is recorded income, not independently verified salary.'})
        else:
            blocks.append({'text': 'Comparable recorded-income totals are unavailable. Import statements covering the requested periods.'})
        ranking_id = 'income_source:' + ('absolute_change' if task == 'income_change' else 'current') + ':3'
        ranking = rankings[ranking_id]
        blocks.append({'ranking': ranking_id})
        prefix = current+'_income_source_'
        source_ids = {k[len(p):] for p in (prefix, previous+'_income_source_')
                      for k in adapter.metrics if k.startswith(p) and k != p+'count'}
        before_sum = sum((decimal(adapter.metrics.get(previous+'_income_source_'+k, 0)) for k in source_ids), decimal(0))
        after_sum = sum((decimal(adapter.metrics.get(current+'_income_source_'+k, 0)) for k in source_ids), decimal(0))
        selected_change = sum((decimal(row['change']) for row in ranking['rows']), decimal(0))
        checks['reconciled'] = present([keys[1]]) and money(after_sum) == money(values[keys[1]])
        if task == 'income_change':
            checks['reconciled'] = checks['reconciled'] and present(keys) and money(before_sum) == money(values[keys[0]])
        checks['unlisted_source_change'] = money(after_sum-before_sum-selected_change)
        checks['ranked_population'] = ranking['population_count']
        if task == 'income_summary' and not present([keys[0]]):
            for row in ranking['rows']:
                for field in ('previous', 'change'):
                    values.pop(row['references'].pop(field), None)
                    row[field] = None
                row['change_percent'] = None
            checks['unlisted_source_change'] = None
        if not checks['reconciled']:
            blocks.append({'text': 'The available source groups do not fully reconcile to the income totals; attribution is incomplete.'})
        elif ranking['population_count'] > len(ranking['rows']):
            blocks.append({'text': 'The ranking shows the largest contributors, not every source. The complete source totals reconcile to recorded income.'})
        else:
            blocks.append({'text': 'These source totals reconcile to recorded income. Changes do not by themselves explain why a payment changed.'})

    if task == 'wealth_change':
        keys = [previous+'_net_worth', current+'_net_worth', 'net_worth_change']
        aligned = availability.get('aligned_wealth', False) and present(keys)
        checks['aligned_wealth'] = aligned
        if aligned:
            if money(decimal(values[keys[1]])-decimal(values[keys[0]])) != money(values[keys[2]]):
                raise ValueError('Wealth reconciliation failed')
            blocks.append({'text': f'Total wealth changed by {ref(keys[2])}, from {ref(keys[0])} to {ref(keys[1])}, using aligned scoped balances.'})
        else:
            blocks.append({'text': 'Total wealth change is unavailable: comparable month-end balances are missing. Add them through Import statements, then return here.'})
        cash_keys = ['income_change', 'net_spending_change', 'money_kept_change']
        if present(cash_keys):
            if money(decimal(values[cash_keys[0]])-decimal(values[cash_keys[1]])) != money(values[cash_keys[2]]):
                raise ValueError('Cash-flow reconciliation failed')
            blocks.append({'text': 'Separately, cash-flow improvement = income change ('+ref(cash_keys[0])+') minus spending change ('+ref(cash_keys[1])+') = '+ref(cash_keys[2])+'. This is not a reconciliation of total wealth.'})
        else:
            blocks.append({'text': 'Comparable cash-flow changes are also unavailable.'})
        blocks.append({'text': 'Investment-performance attribution and funding sources remain unavailable from this chain; recorded income is not verified salary.'})
    return {'task': task, 'required_blocks': blocks, **checks}
