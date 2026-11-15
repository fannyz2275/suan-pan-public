"""User-scoped forecast loading and durable, explicit user overrides."""
from datetime import date
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.engine.forecast import (
    AssumptionPatch, ForecastSettings, apply_overrides, build_assumptions, project_forecast,
)
from app.engine.recurring.schema import RecurringRule


class ForecastUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    overrides: dict[str, AssumptionPatch] = Field(default_factory=dict, max_length=500)
    settings: ForecastSettings | None = None


def _rows(db, table, uid, *, extra=None):
    result = []
    for offset in range(0, 1000000, 1000):
        query = db.table(table).select('*').eq('user_id', uid)
        if extra:
            query = extra(query)
        page = query.order('id').range(offset, offset + 999).execute().data or []
        result.extend(page)
        if len(page) < 1000:
            return result
    raise ValueError('Too many records to load a complete forecast.')


def load_forecast(db, uid: str, *, months=12, update: ForecastUpdate | None = None, today=None):
    today = today or date.today()
    accounts = _rows(db, 'accounts', uid, extra=lambda q: q.eq('is_active', True))
    transactions = _rows(db, 'transactions', uid)
    goals = _rows(db, 'goals', uid, extra=lambda q: q.eq('is_active', True))
    rules = [RecurringRule.model_validate(r) for r in _rows(db, 'recurring_rules', uid)]
    # Missing source tables fail the request rather than silently dropping obligations.
    notes = _rows(db, 'user_notes', uid)
    settings_id = str(uuid5(NAMESPACE_URL, f'suan-pan:{uid}:forecast-settings'))
    saved = next((n.get('provenance') or {} for n in notes if n['id'] == settings_id), {})
    overrides = dict(saved.get('overrides', {}))
    items = build_assumptions(transactions, rules, goals, notes, today=today)
    # If a remembered plan later becomes a saved goal, retain manual edits and
    # disabled state under the canonical goal identity.
    for item in items:
        if item.source != 'goal':
            continue
        aliases = [f'memory:{note_id}' for note_id in item.memory_ids if f'memory:{note_id}' in overrides]
        if len(aliases) == 1:
            previous = overrides.pop(aliases[0])
            overrides.setdefault(item.id, previous)
    settings_data = saved.get('settings')
    default_reserve = 3 * sum(i.monthly_amount for i in items if i.group in {'recurring_costs', 'everyday_spending'})
    settings = ForecastSettings.model_validate(settings_data or {'cash_reserve': default_reserve})
    if update:
        known = {i.id for i in items}
        if set(update.overrides) - known:
            raise ValueError('An assumption changed or is no longer available. Refresh before editing.')
        overrides = {**overrides}
        for key, value in update.overrides.items():
            patch = value.model_dump(exclude_unset=True)
            if not patch:  # Reset only this override to its latest source values.
                overrides.pop(key, None)
            else:
                overrides[key] = {**overrides.get(key, {}), **patch}
        if update.settings is not None:
            settings = update.settings
    items = apply_overrides(items, overrides, today=today)
    result = project_forecast(accounts, items, settings, months=months, today=today)
    result['data_quality'] = {
        'has_history_baseline':any(i.source == 'transactions' and i.group == 'everyday_spending' for i in items),
        'has_income':any(i.group == 'income' for i in items),
        'has_spending':any(i.group in {'recurring_costs', 'everyday_spending'} for i in items),
    }
    if not result['data_quality']['has_history_baseline']:
        result['warnings'].insert(0, 'No everyday-spending baseline from elapsed months. Import complete prior-month statements; spending may be missing.')
    if not result['data_quality']['has_income']:
        result['warnings'].insert(0, 'No usable income estimate. Import income records or review recurring payroll rules.')
    if not accounts:
        result['warnings'].insert(0, 'No account balances available. Add accounts in Wealth before relying on this projection.')
    if not transactions:
        result['warnings'].insert(0, 'No transaction history available. Income and everyday spending may be missing; import statements.')
    if update:
        # Stored as a user-authored preference in the existing notes table. No
        # LLM extraction, embeddings, or new database migration is needed.
        db.table('user_notes').upsert({
            'id':settings_id, 'user_id':uid, 'kind':'preference',
            'content':'Explicit forecast settings and assumption overrides. Do not infer amounts from this note.',
            'tags':['engine:forecast-settings'], 'source':'entity_edit', 'entity_refs':{},
            'provenance':{'overrides':overrides, 'settings':settings.model_dump()},
            'strength':1, 'importance':1,
        }).execute()
    return result
