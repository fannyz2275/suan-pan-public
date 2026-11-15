"""Deterministic contributor arithmetic; no model decisions."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def decimal(value):
    try:
        if isinstance(value, bool):
            raise ValueError('Boolean is not a financial value')
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError('Nonfinite amount')
        return result
    except InvalidOperation as exc:
        raise ValueError('Invalid amount') from exc


def money(value):
    return str(decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def rank_contributors(rows, *, measure='current', limit=5):
    if measure not in {'current', 'change', 'absolute_change'} or type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Invalid ranking request')
    grouped = {}
    for row in rows:
        key = str(row['id'])
        group = grouped.setdefault(key, {'current': Decimal(0), 'previous': Decimal(0)})
        for field in group:
            group[field] += decimal(row.get(field, 0))
    values = []
    for key, row in grouped.items():
        current, previous = row['current'], row['previous']
        change = current - previous
        values.append({'id': key, 'current': money(current), 'previous': money(previous),
                       'change': money(change), 'change_percent': money(change / previous * 100) if previous > 0 else None})
    def rank(row):
        value = decimal(row['change' if measure == 'absolute_change' else measure])
        return -(abs(value) if measure == 'absolute_change' else value), row['id']
    values.sort(key=rank)
    return {'rows': values[:limit], 'measure': measure, 'population_count': len(values),
            'total': money(sum((decimal(v['current']) for v in values), Decimal(0))),
            'remainder': money(sum((decimal(v['current']) for v in values[limit:]), Decimal(0))),
            'tie_policy': 'equal values ordered by stable entity ID'}
