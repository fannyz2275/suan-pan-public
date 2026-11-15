import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, MessageCircle } from 'lucide-react'
import type { AdvisorContext } from '@/lib/advisorContext'
import { fetchSummaryTransactions, localMonth, spendingSummary } from '@/lib/spendingSummary'
import type { Transaction } from '@/lib/categoryBreakdown'
import { formatCurrency } from '@/lib/formatters'
import SpendingCategories from './SpendingCategories'
import RecordedRecurring from './RecordedRecurring'

const metrics = [
  { key: 'income', label: 'Income', formula: 'Sum of positive non-transfer transactions.' },
  { key: 'spending', label: 'Spending', formula: 'Sum of the absolute amounts of negative non-transfer transactions.' },
  { key: 'kept', label: 'Money kept', formula: 'Income minus spending.' },
  { key: 'rate', label: 'Savings rate', formula: '(Income minus spending) / income × 100. Unavailable when income is zero.' },
] as const
type Metric = typeof metrics[number]['key']

export default function SpendingSummary({ refreshKey = 0, detailed = false, onExplain }: { refreshKey?: number; detailed?: boolean; onExplain?: (context: AdvisorContext) => void }) {
  const [month, setMonth] = useState(localMonth)
  return <SummaryData key={refreshKey} month={month} onMonthChange={setMonth} detailed={detailed} onExplain={onExplain} />
}

function SummaryData({ month, onMonthChange, detailed, onExplain }: { month: string; onMonthChange: (month: string) => void; detailed: boolean; onExplain?: (context: AdvisorContext) => void }) {
  const [rows, setRows] = useState<Transaction[] | null>(null)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [expanded, setExpanded] = useState<Metric | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    fetchSummaryTransactions(controller.signal).then(data => {
      if (!controller.signal.aborted) setRows(data)
    }).catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [attempt])
  const result = spendingSummary(rows ?? [], month)
  const selected = metrics.find(m => m.key === expanded)
  const details = result.rows.filter(t => expanded === 'income' ? t.amount > 0 : expanded === 'spending' ? t.amount < 0 : true)
  return (
    <section aria-label="Spending and savings" className="space-y-3 border-b pb-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">Spending and savings</h2>
        <label className="text-sm flex items-center gap-2">Month
          <input type="month" aria-label="Summary month" value={month} max={localMonth()} className="border rounded px-2 py-1 min-w-0" onChange={e => {
            if (/^\d{4}-\d{2}$/.test(e.target.value) && e.target.value <= localMonth()) onMonthChange(e.target.value)
          }} />
        </label>
      </div>
      {error ? <div role="alert" className="text-sm">Could not load spending data. <button className="underline" onClick={() => { setError(false); setAttempt(n => n + 1) }}>Retry</button></div>
        : rows === null ? <p role="status" className="text-sm text-muted-foreground">Loading spending and savings...</p>
        : <>
          <p className="text-xs text-muted-foreground">{result.from} to {result.to} · Imported records; coverage not verified. Transfers marked internal or external are excluded. Positive credits count as income; negative amounts count as spending.</p>
          {result.rows.length === 0 && <p className="text-sm">No transactions for this period. Import statements to see your summary.</p>}
          {result.needsReview > 0 && <p className="text-sm text-amber-700">{result.needsReview} possible transfer{result.needsReview === 1 ? '' : 's'} included pending review. Totals may change.</p>}
          <div className="grid grid-cols-2 gap-3">
            {metrics.map(metric => {
              const value = result.totals[metric.key]
              const now = result.comparison[metric.key], before = result.previous[metric.key]
              const comparable = result.comparisonRows.length > 0 && result.previousRows.length > 0 && now !== null && before !== null
              const delta = comparable ? now! - before! : null
              const Icon = expanded === metric.key ? ChevronUp : ChevronDown
              return <div key={metric.key} className="min-w-0 border rounded-md">
                <button aria-expanded={expanded === metric.key} aria-controls="spending-metric-detail" onClick={() => setExpanded(expanded === metric.key ? null : metric.key)} className="w-full min-w-0 text-left p-3 hover:bg-muted/40">
                <span className="flex justify-between items-center gap-2 text-sm">{metric.label}<Icon size={16} className="shrink-0" /></span>
                <span className="block text-xl font-semibold tabular-nums break-all mt-1">{result.rows.length === 0 || value === null ? 'Unavailable' : metric.key === 'rate' ? `${value.toFixed(1)}%` : formatCurrency(value)}</span>
                <span className="block text-xs text-muted-foreground mt-1">{delta === null ? 'Comparison unavailable' : `${delta > 0 ? '+' : ''}${metric.key === 'rate' ? `${delta.toFixed(1)} pp` : formatCurrency(delta)} vs prior period`}</span>
              </button>
              {onExplain && <button aria-label={`Explain ${metric.label}`} title="Explain this" className="flex items-center gap-1 text-xs px-3 pb-3 text-muted-foreground hover:text-foreground" onClick={() => onExplain({ label: metric.label, prompt: `Explain my ${metric.label.toLowerCase()} for ${month} using this displayed summary. Do not infer missing coverage or treat unavailable data as zero.\n${JSON.stringify({ period: { from: result.from, to: result.to }, metric: metric.key, value: result.rows.length ? value : null, formula: metric.formula, comparison: { from: result.from, to: result.compareTo, previousFrom: result.previousFrom, previousTo: result.previousTo, delta }, coverage: 'Imported records; full coverage unverified. Marked transfers excluded. Positive credits are income, negative amounts are spending.', pendingTransferReview: result.needsReview })}` })}><MessageCircle size={14} />Explain this</button>}
              </div>
            })}
          </div>
          <p className="text-xs text-muted-foreground">Comparison: {result.from}–{result.compareTo} vs {result.previousFrom}–{result.previousTo}. Differences reflect available records, not verified full coverage.</p>
          {selected && <div id="spending-metric-detail" className="space-y-2 border-t pt-3">
            <h3 className="text-sm font-medium">{selected.label} calculation</h3>
            <p className="text-sm text-muted-foreground">{selected.formula}</p>
            <p className="text-xs">Income {formatCurrency(result.totals.income)} · Spending {formatCurrency(result.totals.spending)} · Money kept {formatCurrency(result.totals.kept)}</p>
            <div className="max-h-64 overflow-auto">
              <table className="w-full text-xs"><thead><tr className="border-b"><th className="text-left p-2">Date</th><th className="text-left p-2">Transaction</th><th className="text-right p-2">Amount</th></tr></thead>
                <tbody>{details.map(t => <tr key={t.id} className="border-b"><td className="p-2 whitespace-nowrap">{t.date}</td><td className="p-2 break-words">{t.description || t.category || 'Transaction'}</td><td className="p-2 text-right whitespace-nowrap">{formatCurrency(t.amount)}</td></tr>)}</tbody>
              </table>
            </div>
            {details.length === 0 && <p className="text-sm text-muted-foreground">No matching transactions.</p>}
          </div>}
          {detailed && <SpendingCategories key={month} result={result} />}
          {detailed && <RecordedRecurring key={`recurring-${month}`} result={result} />}
        </>}
    </section>
  )
}
