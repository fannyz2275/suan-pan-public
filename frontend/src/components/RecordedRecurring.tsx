import type { spendingSummary } from '@/lib/spendingSummary'
import { summarize } from '@/lib/spendingSummary'
import { useEffect, useState } from 'react'
import api from '@/lib/api'
import type { RuleBinding } from '@/lib/categoryBreakdown'
import { formatCurrency } from '@/lib/formatters'

export default function RecordedRecurring({ result }: { result: ReturnType<typeof spendingSummary> }) {
  const [bindings, setBindings] = useState<RuleBinding[] | null>(null)
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    api.get<{ bindings: RuleBinding[] }>('/engine/recurring/match', {
      params: { date_from: result.from, date_to: result.to }, signal: controller.signal,
    }).then(({ data }) => { if (!controller.signal.aborted) setBindings(data.bindings) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [result.from, result.to, attempt])
  const ids = new Set(bindings?.map(b => b.transaction_id))
  const rows = result.rows.filter(t => t.amount < 0 && ids.has(t.id)).sort((a, b) => b.date.localeCompare(a.date))
  return <section aria-label="Recorded recurring charges" className="border-t pt-4 space-y-3">
    <h3 className="text-sm font-semibold">Recorded recurring charges</h3>
    {error ? <p role="alert" className="text-sm">Could not load recurring matches. <button className="underline" onClick={() => { setError(false); setAttempt(n => n + 1) }}>Retry</button></p>
      : bindings === null ? <p role="status" className="text-sm text-muted-foreground">Loading recurring matches...</p>
      : <>
        <p className="text-xs text-muted-foreground">{result.from} to {result.to} · Matched against current rules. Already included in spending totals.</p>
        {rows.length ? <>
          <p className="text-sm font-medium">{formatCurrency(summarize(rows).spending)} recorded</p>
          <ul className="divide-y text-xs max-h-64 overflow-auto">{rows.map(t => <li key={t.id} className="flex gap-3 py-2">
            <span className="shrink-0">{t.date}</span><span className="min-w-0 flex-1 break-words">{t.description || t.category || 'Transaction'}</span><span className="shrink-0 tabular-nums">{formatCurrency(-t.amount)}</span>
          </li>)}</ul>
        </> : <p className="text-sm text-muted-foreground">No matched recurring charges recorded in this period.</p>}
      </>}
  </section>
}
