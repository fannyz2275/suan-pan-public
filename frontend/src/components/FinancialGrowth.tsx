import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import api from '@/lib/api'
import { formatCurrency, formatCompactCurrency } from '@/lib/formatters'
import { MessageCircle } from 'lucide-react'
import type { AdvisorContext } from '@/lib/advisorContext'

type Values = { cash: number; investments: number; other: number; debt: number; net_worth: number }
type Unrealized = { value: number | null; known_holdings: number; total_holdings: number; covered_accounts: number; total_accounts: number; oldest_date: string | null; latest_date: string | null }
export interface Growth {
  requested_start: string; baseline_date: string | null; as_of: string; account_count: number
  current: Values; change: number | null; percent_change: number | null
  changes: Omit<Values, 'net_worth'> | null
  balance_dates: { name: string; date: string | null }[]
  series: { date: string; net_worth: number | null; covered_accounts: number }[]
  investments: { net_contributions: number | null; flow_count: number; unrealized: Unrealized; prior_unrealized: Unrealized | null; unrealized_change: number | null }
}
const money = (value: number | null | undefined) => value == null ? 'Unavailable' : formatCurrency(value)
const labels = { cash: 'Cash you can use', investments: 'Investments', other: 'Property and other assets', debt: 'What you owe (subtracted)' }

export default function FinancialGrowth({ refreshKey = 0, onExplain }: { refreshKey?: number; onExplain?: (context: AdvisorContext) => void }) {
  const [window, setWindow] = useState('3M')
  return <section aria-label="Financial growth" className="border-b pb-5 space-y-3">
    <div className="flex flex-wrap justify-between items-center gap-3">
      <h2 className="text-base font-semibold">Financial growth</h2>
      <div role="group" aria-label="Growth period" className="flex gap-1">
        {['3M', '6M', '1Y', 'All'].map(value => <button key={value} aria-pressed={window === value} onClick={() => setWindow(value)} className={`px-2 py-1 text-sm rounded ${window === value ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>{value}</button>)}
      </div>
    </div>
    <GrowthData key={`${window}-${refreshKey}`} window={window} onExplain={onExplain} />
  </section>
}

function GrowthData({ window, onExplain }: { window: string; onExplain?: (context: AdvisorContext) => void }) {
  const [data, setData] = useState<Growth | null>(null)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    api.get<Growth>('/engine/growth', { params: { window }, signal: controller.signal })
      .then(r => { if (!controller.signal.aborted) setData(r.data) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [window, attempt])
  if (error) return <p role="alert" className="text-sm">Could not load financial growth. <button className="underline" onClick={() => { setError(false); setAttempt(n => n + 1) }}>Retry</button></p>
  if (!data) return <p role="status" className="text-sm text-muted-foreground">Loading financial growth...</p>
  if (!data.account_count) return <p className="text-sm text-muted-foreground">Add accounts to see financial growth.</p>
  const investment = data.investments
  const unrealized = investment.unrealized
  const explain = (label: string) => onExplain?.({ label, prompt: `Explain my ${label.toLowerCase()} for the selected ${window} period using this displayed summary. Distinguish contributions from gains; do not treat missing data as zero or balance changes as investment returns.\n${JSON.stringify({ requested_start: data.requested_start, baseline_date: data.baseline_date, as_of: data.as_of, current: data.current, change: data.change, changes: data.changes, investments: data.investments, coverage: 'Current active accounts only. Recorded balances carried forward, not live valuations. Flow coverage unverified; unrealized gains cover only holdings with cost basis.' })}` })
  return <>
    <div className="flex flex-wrap items-end gap-x-8 gap-y-2">
      <div><p className="text-sm text-muted-foreground">What you own minus what you owe</p><p className="text-2xl font-semibold break-all">{money(data.current.net_worth)}</p><p className="text-xs text-muted-foreground">Net worth, based on recorded balances</p></div>
      <div><p className="text-sm text-muted-foreground">Change since {data.baseline_date ?? 'available history'}</p><p className="text-lg font-medium">{money(data.change)}{data.percent_change !== null ? ` (${data.percent_change.toFixed(1)}%)` : ''}</p></div>
    </div>
    {onExplain && <button aria-label="Explain financial growth" title="Explain this" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" onClick={() => explain('Financial growth')}><MessageCircle size={14} />Explain this</button>}
    <p className="text-xs text-muted-foreground">Current active accounts only. Latest recorded balances are carried forward, not live valuations. Missing account history is not treated as zero.</p>
    {!data.baseline_date && <p className="text-sm">Not enough complete account history to calculate growth.</p>}
    {data.baseline_date && data.baseline_date > data.requested_start && <p className="text-sm text-amber-700">Complete account coverage starts {data.baseline_date}; the comparison covers less than the selected period.</p>}
    <div className="h-56 w-full min-w-0" data-testid="growth-chart">
      <ResponsiveContainer width="100%" height="100%"><LineChart data={data.series} margin={{ left: 8, right: 12, top: 12, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" minTickGap={40} tick={{ fontSize: 11 }} />
        <YAxis tickFormatter={formatCompactCurrency} width={70} tick={{ fontSize: 11 }} />
        <Tooltip formatter={value => money(Number(value))} />
        <Line dataKey="net_worth" name="Recorded net worth" type="stepAfter" stroke="#16836b" strokeWidth={2} connectNulls={false} dot={{ r: 3 }} isAnimationActive={false} />
      </LineChart></ResponsiveContainer>
    </div>
    <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b"><th className="py-2 text-left">Breakdown</th><th className="text-right">Current</th><th className="text-right">Change</th></tr></thead>
      <tbody>{(Object.keys(labels) as (keyof typeof labels)[]).map(key => <tr key={key} className="border-b"><th className="py-2 text-left font-normal">{labels[key]}</th><td className="text-right whitespace-nowrap">{money(data.current[key])}</td><td className="text-right whitespace-nowrap">{money(data.changes?.[key])}</td></tr>)}</tbody>
    </table></div>
    <details className="border-t pt-3"><summary className="cursor-pointer text-sm font-medium">Investment contributions and gains</summary>
      {onExplain && <button aria-label="Explain investment contributions and gains" title="Explain this" className="flex items-center gap-1 text-xs mt-3 text-muted-foreground hover:text-foreground" onClick={() => explain('Investment contributions and gains')}><MessageCircle size={14} />Explain this</button>}
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-3 text-sm">
        <div><dt className="text-muted-foreground">Recorded net contributions</dt><dd className="font-medium">{money(investment.net_contributions)}</dd></div>
        <div><dt className="text-muted-foreground">Investment balance change</dt><dd className="font-medium">{money(data.changes?.investments)}</dd></div>
        <div><dt className="text-muted-foreground">Latest recorded unrealized gain/loss</dt><dd className="font-medium">{money(unrealized.value)}</dd></div>
        <div><dt className="text-muted-foreground">Change in unrealized gain/loss</dt><dd className="font-medium">{money(investment.unrealized_change)}</dd></div>
      </dl>
      <p className="text-xs text-muted-foreground mt-3">Contributions reflect recorded transfers into investment accounts minus withdrawals after {data.baseline_date ?? 'an available baseline'}. Flow coverage is not verified; transfers between investment accounts cancel only when both sides are recorded. No recorded flows means unavailable, not zero.</p>
      <p className="text-xs text-muted-foreground mt-2">Unrealized gain/loss is holdings market value minus cost basis, separate from contributions. Cost basis: {unrealized.known_holdings}/{unrealized.total_holdings} holdings; snapshots: {unrealized.covered_accounts}/{unrealized.total_accounts} investment accounts. Latest valuation dates: {unrealized.oldest_date ?? 'unavailable'} to {unrealized.latest_date ?? 'unavailable'}.</p>
      {investment.prior_unrealized && <p className="text-xs text-muted-foreground mt-2">Starting valuation dates: {investment.prior_unrealized.oldest_date ?? 'unavailable'} to {investment.prior_unrealized.latest_date ?? 'unavailable'}. The change compares available snapshots and can include positions bought or sold; it is not a return rate or realized profit.</p>}
    </details>
    <details className="text-sm border-t pt-3"><summary className="cursor-pointer">Balance history and coverage</summary><ul className="max-h-48 overflow-auto text-xs mt-2 space-y-1">{data.series.map(point => <li key={point.date}>{point.date}: {money(point.net_worth)} · {point.covered_accounts}/{data.account_count} accounts</li>)}</ul><p className="text-xs mt-3">Latest account record updates (may differ from statement valuation dates):</p><ul className="text-xs space-y-1 mt-1">{data.balance_dates.map((account, index) => <li key={index}>{account.name}: {account.date?.slice(0, 10) ?? 'Date unavailable'}</li>)}</ul></details>
  </>
}
