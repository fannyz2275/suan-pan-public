import { useCallback, useEffect, useRef, useState } from 'react'
import { RotateCcw, RefreshCw } from 'lucide-react'
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import api from '@/lib/api'
import { formatCompactCurrency, formatCurrencyCents } from '@/lib/formatters'
import { Button } from '@/components/ui/button'

type Settings = { annual_return: number; annual_volatility: number; invest_surplus: number; cash_reserve: number }
type Assumption = {
  id: string; label: string; group: string; source: string; amount: number | null; frequency: string;
  month: string | null; enabled: boolean; reason: string | null; detail: string; edited: boolean; monthly_amount: number;
}
type Point = { month: string; cash_p50: number; wealth_p10: number; wealth_p50: number; wealth_p90: number;
  income: number; spending: number; planned_spending: number; debt_payment: number; contribution: number }
type Forecast = {
  as_of: string; months: number; assumptions: Assumption[]; settings: Settings;
  starting: { net_worth: number }; monthly_totals: Record<string, number>; projection: Point[];
  cash_shortfall_probability: number; all_goals_funded_probability: number | null;
  goals: { id: string; label: string; month: string; amount: number; funding_probability: number }[];
  warnings: string[];
  data_quality: { has_history_baseline: boolean; has_income: boolean; has_spending: boolean };
}

const frequencies: Record<string, string> = { weekly: 'Weekly', biweekly: 'Bi-weekly', semi_monthly: 'Twice a month', monthly: 'Monthly', quarterly: 'Quarterly', semi_annual: 'Twice a year', annual: 'Annually' }
const groups: Record<string, string> = { income: 'Income', recurring_costs: 'Recurring costs', everyday_spending: 'Everyday spending', planned_spending: 'Planned spending', savings_goals: 'Savings targets', debt_payoff: 'Debt payments' }
const sourceLabels: Record<string, string> = { recurring: 'Recurring rule', transactions: 'Transaction history', goal: 'Saved goal', memory: 'Conversation memory' }
const dollars = formatCurrencyCents
const percent = (value: number) => `${(value * 100).toFixed(0)}%`
const fieldClass = 'h-9 w-full min-w-0 rounded border bg-background px-2 text-sm tabular-nums'

export default function ForecastPanel({ refreshKey = 0 }: { refreshKey?: number }) {
  const [months, setMonths] = useState(12)
  const [data, setData] = useState<Forecast | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const sequence = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const load = useCallback(async (patch?: object) => {
    const id = ++sequence.current
    controller.current?.abort()
    const abort = new AbortController()
    controller.current = abort
    setBusy(true)
    setError('')
    try {
      const config = { params: { months }, signal: abort.signal, timeout: 20000 }
      const response = patch ? await api.patch<Forecast>('/engine/forecast', patch, config) : await api.get<Forecast>('/engine/forecast', config)
      if (!Array.isArray(response.data?.projection) || !Array.isArray(response.data?.assumptions) || !response.data?.data_quality) throw new Error('Invalid forecast response')
      if (id === sequence.current && !abort.signal.aborted) setData(response.data)
    } catch {
      if (id === sequence.current && !abort.signal.aborted) setError(patch ? 'Could not confirm this change was saved. Refresh to check the saved assumptions.' : 'Forecast unavailable. Check your connection and try again.')
    } finally {
      if (id === sequence.current && !abort.signal.aborted) { setBusy(false); setRevision(r => r + 1) }
    }
  }, [months])
  useEffect(() => { void load(); return () => { controller.current?.abort() } }, [load, refreshKey])
  const edit = (id: string, patch: object) => void load({ overrides: { [id]: patch } })
  const changeSetting = (key: keyof Settings, value: number) => data && void load({ settings: { ...data.settings, [key]: value } })
  const final = data?.projection.at(-1)
  const third = data?.projection[2]

  return <section aria-label="Financial forecast" className="space-y-4 border-t pt-4" aria-busy={busy}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-base font-semibold">Cash and wealth forecast</h2>
      <div className="flex items-center gap-2">
        <label className="text-sm">Horizon <select aria-label="Forecast horizon" className="h-9 rounded border bg-background px-2" value={months} disabled={busy} onChange={e => setMonths(Number(e.target.value))}>
          <option value={12}>1 year</option><option value={60}>5 years</option><option value={120}>10 years</option><option value={360}>30 years</option>
        </select></label>
        <Button variant="ghost" size="icon" title="Refresh forecast" aria-label="Refresh forecast" disabled={busy} onClick={() => void load()}><RefreshCw size={16} /></Button>
      </div>
    </div>
    {busy && <p role="status" className="text-sm text-muted-foreground">Updating forecast...</p>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {data && final && <>
      <p className="text-xs text-muted-foreground">Prepared {data.as_of} using latest imported balances. Projection begins next month; remaining current-month activity is not included.</p>
      {(!data.data_quality.has_history_baseline || !data.data_quality.has_income || !data.data_quality.has_spending) && <p className="text-sm text-amber-800" role="status">Incomplete income or everyday-spending estimates. Import complete prior-month statements before relying on this forecast.</p>}
      <div className={busy || error ? 'opacity-60' : ''}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div><p className="text-sm text-muted-foreground">Cash in three months</p><p data-testid="forecast-cash" className="text-xl font-semibold tabular-nums">{third ? dollars(third.cash_p50) : 'Unavailable'}</p></div>
          <div><p className="text-sm text-muted-foreground">Typical wealth by {final.month}</p><p data-testid="forecast-wealth" className="text-xl font-semibold tabular-nums">{dollars(final.wealth_p50)}</p><p className="text-xs text-muted-foreground">Middle 80%: {dollars(final.wealth_p10)} to {dollars(final.wealth_p90)}</p></div>
          <div><p className="text-sm text-muted-foreground">Cash shortfall risk</p><p className="text-xl font-semibold tabular-nums">{percent(data.cash_shortfall_probability)}</p><p className="text-xs text-muted-foreground">Across this forecast horizon</p></div>
        </div>
        <div className="mt-4 h-64 w-full min-w-0" aria-label="Projected wealth range and cash">
          <ResponsiveContainer width="100%" height="100%"><ComposedChart data={data.projection.map(p => ({ ...p, range: [p.wealth_p10, p.wealth_p90] }))} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="month" minTickGap={40} tick={{ fontSize: 11 }} /><YAxis tickFormatter={formatCompactCurrency} tick={{ fontSize: 11 }} width={64} />
            <Tooltip formatter={(v) => Array.isArray(v) ? v.map(n => dollars(Number(n))).join(' to ') : dollars(Number(v))} />
            <Area dataKey="range" name="Middle 80% of wealth outcomes" fill="#d1fae5" stroke="none" isAnimationActive={false} />
            <Line dataKey="wealth_p50" name="Typical wealth" stroke="#047857" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line dataKey="cash_p50" name="Cash" stroke="#d97706" dot={false} strokeWidth={2} isAnimationActive={false} />
          </ComposedChart></ResponsiveContainer>
        </div>
        <p className="text-xs text-muted-foreground">Wealth: green. Cash: amber. Future dollars; investment-return uncertainty only.</p>
      </div>
      <details open className="border-t pt-3">
        <summary className="cursor-pointer text-sm font-semibold">Forecast assumptions</summary>
        <fieldset disabled={busy} className="min-w-0 space-y-5 pt-4" key={revision}>
          {Object.entries(groups).map(([key, title]) => {
            const items = data.assumptions.filter(i => i.group === key)
            if (!items.length) return null
            return <div key={key} role="group" aria-label={title} className="min-w-0">
              <div className="flex flex-wrap justify-between gap-2 border-b pb-2"><h3 className="text-sm font-semibold">{title}</h3>{key in data.monthly_totals && <span data-testid={`total-${key}`} className="text-sm tabular-nums">{dollars(data.monthly_totals[key])}/month equivalent</span>}</div>
              {items.map(item => <div key={item.id} className="grid min-w-0 grid-cols-[minmax(0,1fr)_2rem] gap-2 border-b py-3 sm:grid-cols-[minmax(0,1fr)_8rem_10rem_2rem]" data-testid={`assumption-${item.id}`}>
                <div className="min-w-0">
                  <label className="flex items-start gap-2 text-sm font-medium"><input type="checkbox" className="mt-1" aria-label={`Include ${item.label}`} defaultChecked={item.enabled} onChange={e => edit(item.id, { enabled: e.target.checked })} /><span className="break-words">{item.label}</span></label>
                  <p className="ml-5 text-xs text-muted-foreground">{sourceLabels[item.source]}{item.edited ? ' · Your override' : ''}</p>
                  {item.frequency !== 'once' && <p className="ml-5 text-xs tabular-nums">{dollars(item.monthly_amount)}/month equivalent</p>}
                  {item.reason && <p className="ml-5 text-xs text-amber-800">{item.reason}</p>}
                  <details className="ml-5 text-xs text-muted-foreground"><summary className="cursor-pointer">Source details</summary><p className="mt-1">{item.detail}</p></details>
                </div>
                <label className="col-start-1 text-xs text-muted-foreground sm:col-auto">Amount ($)<input aria-label={`Amount for ${item.label}`} className={fieldClass} type="number" min="0" max="1000000000000" step="0.01" defaultValue={item.amount ?? ''} onBlur={e => {
                  if (e.target.validity.valid && e.target.value !== '' && Number(e.target.value) !== item.amount) edit(item.id, { amount: Number(e.target.value) })
                }} /></label>
                {item.frequency === 'once' ? <label className="col-start-1 text-xs text-muted-foreground sm:col-auto">Month<input aria-label={`Month for ${item.label}`} className={fieldClass} type="month" defaultValue={item.month ?? ''} onBlur={e => { if (e.target.validity.valid && e.target.value && e.target.value !== item.month) edit(item.id, { month: e.target.value }) }} /></label>
                  : <label className="col-start-1 text-xs text-muted-foreground sm:col-auto">Frequency<select aria-label={`Frequency for ${item.label}`} className={fieldClass} value={item.frequency} onChange={e => edit(item.id, { frequency: e.target.value })}>{Object.entries(frequencies).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>}
                <Button className="col-start-2 row-start-1 sm:col-auto sm:row-auto" size="icon" variant="ghost" aria-label={`Reset ${item.label}`} title="Restore source values" disabled={!item.edited} onClick={() => edit(item.id, {})}><RotateCcw size={14} /></Button>
              </div>)}
            </div>
          })}
          <div role="group" aria-label="Investing assumptions" className="grid grid-cols-1 gap-3 border-t pt-3 sm:grid-cols-2">
            {([{ key: 'cash_reserve', label: 'Cash reserve ($)', factor: 1, max: 1e12 }, { key: 'invest_surplus', label: 'Invest share of monthly surplus (%)', factor: 100, max: 100 }, { key: 'annual_return', label: 'Expected annual investment return (%)', factor: 100, min: -50, max: 50 }, { key: 'annual_volatility', label: 'Annual investment volatility (%)', factor: 100, max: 100 }] as const).map(field => <label key={field.key} className="text-xs">{field.label}<input aria-label={field.label} className={fieldClass} type="number" min={'min' in field ? field.min : 0} max={field.max} step="0.01" defaultValue={Number((data.settings[field.key] * field.factor).toFixed(2))} onBlur={e => { if (e.target.validity.valid && e.target.value && Number(e.target.value) / field.factor !== data.settings[field.key]) changeSetting(field.key, Number(e.target.value) / field.factor) }} /></label>)}
          </div>
          <p className="text-xs text-muted-foreground">Contributions use positive monthly surplus after protecting your cash reserve and the next 12 months of planned commitments. Forecast overrides do not change your saved goals or recurring rules.</p>
        </fieldset>
      </details>
      {!!data.goals.length && <div className="border-t pt-3"><h3 className="text-sm font-semibold">Goals in this forecast</h3>{data.goals.map(g => <p key={g.id} className="mt-2 text-sm">{g.label}: {dollars(g.amount)} in {g.month} · {percent(g.funding_probability)} funded from available cash</p>)}<p className="mt-2 text-sm">All scheduled goals funded: {percent(data.all_goals_funded_probability ?? 0)}</p></div>}
      <details className="border-t pt-3"><summary className="cursor-pointer text-sm">Monthly numbers and limitations</summary>
        <div className="overflow-x-auto"><table className="mt-3 w-full text-right text-xs tabular-nums"><thead><tr>{['Month', 'Income', 'Everyday + recurring', 'Planned spending', 'Debt paid', 'Invested', 'Cash', 'Typical wealth'].map(h => <th key={h} className="p-2 whitespace-nowrap">{h}</th>)}</tr></thead><tbody>{data.projection.map(p => <tr key={p.month} data-testid={`forecast-month-${p.month}`}>{[p.month, dollars(p.income), dollars(p.spending), dollars(p.planned_spending), dollars(p.debt_payment), dollars(p.contribution), dollars(p.cash_p50), dollars(p.wealth_p50)].map((v, i) => <td key={i} className="border-t p-2 whitespace-nowrap">{v}</td>)}</tr>)}</tbody></table></div>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted-foreground">{data.warnings.map(w => <li key={w}>{w}</li>)}</ul>
      </details>
    </>}
  </section>
}
