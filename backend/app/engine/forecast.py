"""Shared monthly cash ledger and wealth simulation. No model-generated arithmetic."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Literal

import numpy as np
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, ConfigDict, Field

from app.engine.cashflow import FREQ_PER_YEAR
from app.engine.recurring.rule_match import apply_rule_matches
from app.engine.snapshot import compute_snapshot


class ForecastSettings(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    annual_return: float = Field(default=0.07, ge=-0.5, le=0.5)
    annual_volatility: float = Field(default=0.15, ge=0, le=1)
    invest_surplus: float = Field(default=1, ge=0, le=1)
    cash_reserve: float = Field(default=0, ge=0, le=1e12)


class Assumption(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    id: str
    label: str
    group: Literal['income', 'recurring_costs', 'everyday_spending', 'planned_spending', 'savings_goals', 'debt_payoff']
    source: Literal['transactions', 'recurring', 'goal', 'memory']
    amount: float | None = Field(default=None, ge=0, le=1e12)
    frequency: Literal['weekly', 'biweekly', 'semi_monthly', 'monthly', 'quarterly', 'semi_annual', 'annual', 'once'] = 'monthly'
    month: str | None = Field(default=None, pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    anchor: date | None = None
    enabled: bool = True
    reason: str | None = None
    detail: str = ''
    edited: bool = False
    memory_ids: list[str] = Field(default_factory=list)

    @property
    def monthly_amount(self) -> float:
        if not self.enabled or self.amount is None or self.frequency == 'once':
            return 0.0
        return round(self.amount * FREQ_PER_YEAR[self.frequency] / 12, 2)


class AssumptionPatch(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    enabled: bool | None = None
    amount: float | None = Field(default=None, ge=0, le=1e12)
    frequency: Literal['weekly', 'biweekly', 'semi_monthly', 'monthly', 'quarterly', 'semi_annual', 'annual', 'once'] | None = None
    month: str | None = Field(default=None, pattern=r'^\d{4}-(0[1-9]|1[0-2])$')


def event_key(label: str) -> str:
    words = ''.join(c.lower() if c.isalnum() else ' ' for c in label).split()
    return '-'.join(w for w in words if w not in {'my', 'our', 'the', 'planned', 'plan', 'cost', 'budget'})


def _linked_goal(event, goals):
    explicit = next((g for g in goals if str(g['id']) == str(event.get('goal_id'))), None)
    if explicit:
        return explicit
    if event.get('new_event'):
        return None
    matches = [g for g in goals if event_key(g['name']) == event_key(event.get('label', ''))
               and (not event.get('month') or event['month'] == str(g['target_date'])[:7])]
    return matches[0] if len(matches) == 1 else None


def build_assumptions(transactions, rules, goals, notes, *, today: date) -> list[Assumption]:
    first = today.replace(day=1)
    cutoff = first - relativedelta(months=6)
    rows = [t for t in transactions if cutoff.isoformat() <= str(t.get('date', '')) < first.isoformat()
            and t.get('category') != 'transfer'
            and t.get('transfer_status') not in {'auto_paired', 'user_confirmed_internal', 'external'}]
    active = [r for r in rules if r.status in {'auto_applied', 'user_confirmed'}]
    bindings = apply_rule_matches(rows, active).bindings
    sample_ids = {str(tid) for r in active for tid in r.sample_transaction_ids}
    out = [Assumption(id=f'recurring:{r.id}', label=r.keyword, source='recurring',
                      group='income' if r.direction == 'income' else 'recurring_costs',
                      amount=r.amount_median, frequency=r.frequency,
                      anchor=r.last_seen_date or r.next_expected_date,
                      detail='Per payment; monthly equivalent uses payments per year / 12.' +
                             (' Dates estimated: no last payment date.' if not (r.last_seen_date or r.next_expected_date) else ''))
           for r in active]
    # Use one observed calendar window for every category, including zero months.
    # Starting at the first observed month avoids inventing coverage before imports.
    observed_start = min((str(t['date'])[:7] for t in rows), default=None)
    month_keys = []
    cursor = date.fromisoformat(observed_start + '-01') if observed_start else first
    while cursor < first:
        month_keys.append(cursor.strftime('%Y-%m'))
        cursor += relativedelta(months=1)
    buckets = defaultdict(lambda: defaultdict(float))
    for t in rows:
        if str(t.get('id')) in bindings or str(t.get('id')) in sample_ids:
            continue
        category = t.get('category') or 'other'
        amount = float(t.get('amount') or 0)
        if category == 'income':
            buckets[('income', 'Other income')][str(t['date'])[:7]] += amount
        else:
            # Positive expense-category rows are refunds, not additional income.
            buckets[('everyday_spending', category)][str(t['date'])[:7]] -= amount
    for (group, category), totals in sorted(buckets.items()):
        amount = max(0.0, median([totals.get(m, 0) for m in month_keys]))
        out.append(Assumption(id=f'history:{group}:{category}', label=category.replace('_', ' ').capitalize(),
                              group=group, source='transactions', amount=round(amount, 2),
                              detail=f'Median of {len(month_keys)} elapsed months ({month_keys[0]} to {month_keys[-1]}), including zero months. Import coverage may be incomplete.'))
    for g in goals:
        group = {'life_event':'planned_spending', 'debt_payoff':'debt_payoff'}.get(g.get('type'), 'savings_goals')
        out.append(Assumption(id=f"goal:{g['id']}", label=g['name'], group=group, source='goal',
                              amount=g.get('target_amount'), frequency='once', month=str(g['target_date'])[:7],
                              detail='Full target amount; saved progress is already part of account balances.'))
    for n in notes:
        event = (n.get('provenance') or {}).get('forecast_event')
        if not event or event.get('cancelled') or n.get('superseded_by') or (n.get('expires_at') and str(n['expires_at'])[:10] <= today.isoformat()):
            continue
        key = event_key(event.get('label') or '')
        linked = _linked_goal(event, goals)
        if linked:
            next(i for i in out if i.id == f"goal:{linked['id']}").memory_ids.append(n['id'])
        if not key or linked:
            continue
        out.append(Assumption(id=f"memory:{n['id']}", label=event['label'], group='planned_spending', source='memory',
                              amount=event.get('amount'), frequency='once', month=event.get('month'),
                              detail='Estimated future expense from conversation memory; automatically included when amount and month are known.'))
    for item in out:
        item.reason = _reason(item, today)
    return out


def _reason(item: Assumption, today: date) -> str | None:
    if item.amount is None:
        return 'Not modeled yet: amount missing.'
    if item.frequency == 'once':
        if not item.month:
            return 'Not modeled yet: month missing.'
        if item.month <= today.strftime('%Y-%m'):
            return 'Not modeled: date is in the current or a past month. Choose a future month.'
    return None


def apply_overrides(items, overrides, *, today):
    result = []
    for original in items:
        patch = AssumptionPatch.model_validate(overrides.get(original.id, {})).model_dump(exclude_unset=True)
        item = Assumption.model_validate({**original.model_dump(), **patch, 'edited': bool(patch)})
        if (original.frequency == 'once') != (item.frequency == 'once'):
            raise ValueError('One-time goals cannot become recurring payments.')
        item.reason = _reason(item, today)
        result.append(item)
    return result


def _scheduled_amount(item: Assumption, month: date) -> float:
    if not item.enabled or item.reason or item.amount is None:
        return 0.0
    if item.frequency == 'once':
        return item.amount if item.month == month.strftime('%Y-%m') else 0.0
    anchor = item.anchor
    if not anchor:
        return item.monthly_amount
    end = month + relativedelta(months=1)
    if item.frequency in {'weekly', 'biweekly'}:
        step = 7 if item.frequency == 'weekly' else 14
        offset = max(0, ((month - anchor).days + step - 1) // step)
        cursor = anchor + timedelta(days=offset * step)
        return item.amount * max(0, ((end - cursor).days + step - 1) // step)
    if item.frequency == 'semi_monthly':
        return item.amount * 2 if end > anchor else 0.0
    cycle = {'monthly':1, 'quarterly':3, 'semi_annual':6, 'annual':12}[item.frequency]
    delta = (month.year - anchor.year) * 12 + month.month - anchor.month
    return item.amount if delta >= 0 and delta % cycle == 0 else 0.0


def project_forecast(accounts, items, settings: ForecastSettings, *, months: int, today: date) -> dict:
    if not 1 <= months <= 360:
        raise ValueError('Forecast horizon must be 1 to 360 months.')
    snapshot = compute_snapshot(accounts)
    n = 2000
    cash = np.full(n, float(snapshot['liquid_assets']))
    investments = np.full(n, float(snapshot['investment_assets']))
    debt = float(snapshot['total_liabilities'])
    other = float(snapshot['non_current_assets'])
    initial_wealth = float(snapshot['net_worth'])
    reserved = np.zeros(n)
    ever_short = np.zeros(n, dtype=bool)
    all_goals = np.ones(n, dtype=bool)
    # Lognormal gross returns cannot drive investments below zero. Annual return
    # is an expected nominal return, not a promise or asset-specific calibration.
    rng = np.random.default_rng(129)
    projection, goals = [], []
    current = today.replace(day=1)
    inflows = outflows = contributions = 0.0
    investment_gains = np.zeros(n)
    for index in range(months):
        month = current + relativedelta(months=index + 1)
        z = rng.standard_normal(n)
        gross = np.exp((np.log1p(settings.annual_return) - settings.annual_volatility**2 / 2) / 12
                       + settings.annual_volatility / np.sqrt(12) * z)
        gains = investments * (gross - 1)
        investments += gains
        investment_gains += gains
        income = costs = 0.0
        due = []
        for item in items:
            amount = _scheduled_amount(item, month)
            if item.frequency == 'once':
                if amount:
                    due.append((item, amount))
            elif item.group == 'income':
                income += amount
            else:
                costs += amount
        cash += income - costs
        planned = paid_debt = 0.0
        for item, amount in sorted(due, key=lambda pair: pair[0].id):
            available = cash - reserved
            if item.group == 'debt_payoff':
                payment = min(amount, debt)
                success = available >= payment
                cash -= payment
                debt -= payment
                paid_debt += payment
            elif item.group == 'savings_goals':
                success = available >= amount
                reserved += np.minimum(np.maximum(available, 0), amount)
            else:
                success = available >= amount
                cash -= amount
                planned += amount
            all_goals &= success
            goals.append({'id':item.id, 'label':item.label, 'month':item.month,
                          'amount':payment if item.group == 'debt_payoff' else amount,
                          'target_amount':amount, 'funding_probability':round(float(success.mean()), 4)})
        # Keep the next 12 months of dated commitments in cash. A savings target
        # earmarks funds; an event consumes them. Neither creates new money.
        upcoming_items = [i for i in items if i.enabled and not i.reason and i.frequency == 'once'
                          and month.strftime('%Y-%m') < (i.month or '') <= (month + relativedelta(months=12)).strftime('%Y-%m')]
        upcoming = sum(float(i.amount or 0) for i in upcoming_items if i.group != 'debt_payoff')
        upcoming += min(debt, sum(float(i.amount or 0) for i in upcoming_items if i.group == 'debt_payoff'))
        contribution = np.minimum(np.maximum(cash - reserved - settings.cash_reserve - upcoming, 0),
                                  max(0, income - costs) * settings.invest_surplus)
        cash -= contribution
        investments += contribution
        ever_short |= cash < 0
        wealth = cash + investments + other - debt
        inflows += income
        outflows += costs + planned
        contributions += float(np.median(contribution))
        row = {'month':month.strftime('%Y-%m'), 'income':round(income, 2), 'spending':round(costs, 2),
               'planned_spending':round(planned, 2), 'debt_payment':round(paid_debt, 2),
               'contribution':round(float(np.median(contribution)), 2),
               'shortfall_probability':round(float((cash < 0).mean()), 4)}
        for name, values in [('cash', cash), ('investments', investments), ('wealth', wealth)]:
            for percentile in [10, 50, 90]:
                row[f'{name}_p{percentile}'] = round(float(np.percentile(values, percentile)), 2)
        projection.append(row)
    totals = {group:round(sum(i.monthly_amount for i in items if i.group == group and not i.reason), 2)
              for group in ['income', 'recurring_costs', 'everyday_spending']}
    return {'as_of':today.isoformat(), 'months':months, 'seed':129, 'simulations':n,
            'starting':snapshot, 'settings':settings.model_dump(),
            'assumptions':[{**i.model_dump(mode='json'), 'monthly_amount':i.monthly_amount} for i in items],
            'monthly_totals':totals, 'projection':projection, 'goals':goals,
            'cash_shortfall_probability':round(float(ever_short.mean()), 4),
            'all_goals_funded_probability':round(float(all_goals.mean()), 4) if goals else None,
            'reconciliation':{'starting_wealth':initial_wealth, 'income':round(inflows, 2),
                              'spending':round(outflows, 2), 'investment_gains_p50':round(float(np.median(investment_gains)), 2),
                              'ending_wealth_p50':projection[-1]['wealth_p50'], 'contributions':round(contributions, 2)},
            'warnings':['Estimates in future dollars; no inflation, tax, debt-interest, or property-growth model.',
                        'Projection starts next calendar month using current balances; remaining current-month cash flow is not modeled.',
                        'Investment returns vary; income and spending remain fixed except scheduled payments.',
                        'No automatic investment sales or retirement withdrawals. Negative cash is an unfunded gap, not an approved loan.',
                        'Existing non-cash assets stay unchanged; RSU vesting is not added again as income.',
                        'Savings goals reserve existing cash; life-event goals spend the full target at their date.']}
