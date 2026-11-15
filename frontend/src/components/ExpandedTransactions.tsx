import type { RuleBinding, Transaction } from '@/lib/categoryBreakdown'
import { formatCurrencyCentsSigned as fmt } from '@/lib/formatters'

interface Props {
  transactions: Transaction[]
  bindingByTxnId: Record<string, RuleBinding>
  ruleCountsInWindow: Record<string, number>
}

function fmtDate(iso: string) {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  return dt.toLocaleString('en-US', { month: 'short', day: '2-digit' })
}

const ROW_HEIGHT_PX = 28
const MAX_VISIBLE_ROWS = 5

export default function ExpandedTransactions({ transactions, bindingByTxnId, ruleCountsInWindow }: Props) {
  const sorted = [...transactions].sort((a, b) => (a.date < b.date ? 1 : -1))

  return (
    <div
      className="overflow-y-auto border-t bg-muted/30"
      style={{ maxHeight: ROW_HEIGHT_PX * MAX_VISIBLE_ROWS }}
    >
      <ul className="divide-y text-xs" data-testid="expanded-panel">
        {sorted.map((t) => {
          const binding = bindingByTxnId[t.id]
          const needsReview = t.transfer_status === 'needs_review'
          const count = binding ? ruleCountsInWindow[binding.rule_id] ?? 0 : 0
          return (
            <li
              key={t.id}
              className={`flex items-center gap-3 px-3 ${needsReview ? 'bg-amber-50/60 dark:bg-amber-950/20' : ''}`}
              style={{ height: ROW_HEIGHT_PX }}
            >
              <span className="text-muted-foreground font-mono tabular-nums w-14 shrink-0">
                {fmtDate(t.date)}
              </span>
              <span className="flex-1 truncate" title={t.description ?? ''}>
                {t.description ?? '(no description)'}
              </span>
              <span
                className={`tabular-nums font-medium w-24 text-right ${
                  t.amount > 0
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : t.amount < 0
                      ? 'text-destructive'
                      : 'text-muted-foreground'
                }`}
              >
                {fmt(t.amount)}
              </span>
              <span className="w-20 flex items-center gap-1 shrink-0 text-xs">
                {binding && (
                  <span
                    title={`Recurring: ${binding.rule_keyword} · ${binding.rule_frequency}`}
                    className="text-sky-700 dark:text-sky-400"
                    aria-label="recurring"
                  >
                    ↻ ×{count}
                  </span>
                )}
                {needsReview && (
                  <span
                    title="Pending transfer review"
                    className="text-amber-700 dark:text-amber-400"
                    aria-label="needs review"
                  >
                    ⚠
                  </span>
                )}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
