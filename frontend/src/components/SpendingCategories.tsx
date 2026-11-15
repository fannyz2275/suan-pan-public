import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { spendingSummary, summarize } from '@/lib/spendingSummary'
import { formatCurrency } from '@/lib/formatters'

export default function SpendingCategories({ result }: { result: ReturnType<typeof spendingSummary> }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const categoryOf = (category: string | null) => category?.trim() || 'Uncategorized'
  const categories = [...new Set([...result.rows, ...result.previousRows]
    .filter(t => t.amount < 0).map(t => categoryOf(t.category)))].map(category => {
    const rows = result.rows.filter(t => t.amount < 0 && categoryOf(t.category) === category)
    const current = summarize(rows).spending
    const comparable = summarize(result.comparisonRows.filter(t => categoryOf(t.category) === category)).spending
    const previous = summarize(result.previousRows.filter(t => categoryOf(t.category) === category)).spending
    const delta = result.comparisonRows.length && result.previousRows.length ? Math.round((comparable - previous) * 100) / 100 : null
    return { category, rows, current, delta }
  }).sort((a, b) => Math.abs(b.delta ?? b.current) - Math.abs(a.delta ?? a.current) || a.category.localeCompare(b.category))

  return <section aria-label="Spending by category" className="border-t pt-4 space-y-3">
    <h3 className="text-sm font-semibold">Spending by category</h3>
    <p className="text-xs text-muted-foreground">Largest changes first. Positive changes mean more spending. Credits are counted as income, not netted against categories.</p>
    {categories.length === 0 && <p className="text-sm text-muted-foreground">No spending recorded in either period.</p>}
    <div className="divide-y">
      {categories.map(({ category, rows, current, delta }) => {
        const open = expanded === category
        const Icon = open ? ChevronUp : ChevronDown
        return <div key={category}>
          <button className="w-full flex items-center justify-between gap-3 py-3 text-left hover:bg-muted/30" aria-expanded={open} onClick={() => setExpanded(open ? null : category)}>
            <span className="min-w-0 break-words text-sm">{category}<span className="block text-xs text-muted-foreground">{rows.length} transactions</span></span>
            <span className="shrink-0 text-right text-sm tabular-nums">{result.rows.length ? formatCurrency(current) : 'Unavailable'}<span className="block text-xs text-muted-foreground">{delta === null ? 'Comparison unavailable' : `${delta > 0 ? '+' : ''}${formatCurrency(delta)} vs prior period`}</span></span>
            <Icon size={16} className="shrink-0" />
          </button>
          {open && <div className="max-h-64 overflow-auto pb-3">
            {rows.length === 0 ? <p className="text-sm text-muted-foreground">No spending recorded for this category in the selected period.</p> : <ul className="divide-y text-xs">
              {[...rows].sort((a, b) => b.date.localeCompare(a.date)).map(t => <li key={t.id} className="flex gap-3 py-2">
                <span className="shrink-0 tabular-nums">{t.date}</span>
                <span className="min-w-0 flex-1 break-words">{t.description || 'Transaction'}{t.transfer_status === 'needs_review' && <span className="block text-amber-700">Pending transfer review</span>}</span>
                <span className="shrink-0 tabular-nums">{formatCurrency(-t.amount)}</span>
              </li>)}
            </ul>}
          </div>}
        </div>
      })}
    </div>
  </section>
}
