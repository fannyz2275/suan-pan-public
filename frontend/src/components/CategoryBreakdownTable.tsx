import React, { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import api from '@/lib/api'
import { formatCurrencySigned as fmtMoney } from '@/lib/formatters'
import {
  computeBreakdown,
  computeAnchor,
  RANGE_MONTHS,
  type Range,
  type RuleBinding,
  type Transaction,
} from '@/lib/categoryBreakdown'
import ExpandedTransactions from './ExpandedTransactions'

interface Props {
  refreshKey?: number
}

function fmtMonth(ym: string) {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 1, 1)
  return d.toLocaleString('en-US', { month: 'short', year: '2-digit' })
}

function amountClass(n: number) {
  if (n > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (n < 0) return 'text-destructive'
  return 'text-muted-foreground'
}

export default function CategoryBreakdownTable({ refreshKey = 0 }: Props) {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [bindings, setBindings] = useState<RuleBinding[]>([])
  const [range, setRange] = useState<Range>('3M')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [expandedCell, setExpandedCell] = useState<{ month: string; category: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get<Transaction[]>('/finance/transactions', { params: { limit: 2000 } })
      .then((r) => {
        if (cancelled) return
        setTransactions(r.data)
        setError(false)
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  const anchor = useMemo(() => computeAnchor(transactions), [transactions])

  // Load recurring bindings for the visible window. Depends on the anchor
  // because the anchor defines window endpoints; refetching on range change
  // keeps ruleCountsInWindow scaled to what the user sees.
  useEffect(() => {
    if (transactions.length === 0) return
    let cancelled = false
    const windowMonths = RANGE_MONTHS[range]
    const endMonth = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0)
    const startMonth = new Date(anchor.getFullYear(), anchor.getMonth() - windowMonths + 1, 1)
    const iso = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    api
      .get<{ bindings: RuleBinding[] }>('/engine/recurring/match', {
        params: { date_from: iso(startMonth), date_to: iso(endMonth) },
      })
      .then((r) => {
        if (!cancelled) setBindings(r.data.bindings ?? [])
      })
      .catch(() => {
        if (!cancelled) setBindings([])
      })
    return () => {
      cancelled = true
    }
  }, [anchor, range, transactions.length, refreshKey])

  const breakdown = useMemo(
    () => computeBreakdown(transactions, bindings, range, anchor),
    [transactions, bindings, range, anchor],
  )

  // Derive the effective cell at render time so a stale expandedCell (e.g.
  // after switching ranges) silently collapses without a setState-in-effect.
  const activeCell = expandedCell && breakdown.cells[expandedCell.month]?.[expandedCell.category]
    ? expandedCell
    : null

  function toggleCell(month: string, category: string) {
    setExpandedCell((prev) =>
      prev && prev.month === month && prev.category === category ? null : { month, category },
    )
  }

  if (loading) {
    return (
      <Card>
        <CardContent className="p-6 text-muted-foreground text-sm">Loading…</CardContent>
      </Card>
    )
  }
  if (error) {
    return (
      <Card>
        <CardContent className="p-6 text-muted-foreground text-sm">
          Could not load transactions. Try refreshing.
        </CardContent>
      </Card>
    )
  }
  if (transactions.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Category breakdown</CardTitle>
            <div className="flex gap-1">
              {(['1M', '3M', '6M', '1Y'] as Range[]).map((r) => (
                <button
                  type="button"
                  key={r}
                  onClick={() => setRange(r)}
                  className={`px-2 py-1 text-xs rounded font-medium transition-colors ${
                    range === r
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-8">
            No transactions yet — import to see a breakdown.
          </p>
        </CardContent>
      </Card>
    )
  }

  const { months, categories, cells, rowTotals, colTotals, grand } = breakdown
  const monthsDescending = [...months]

  // Max magnitude per totals column across months — used to scale the
  // in-cell background bar. Keeps each column's bars comparable across rows
  // without tying Inflow's scale to Outflow's (they differ by orders of mag
  // for some users).
  const totalsMax = months.reduce(
    (acc, m) => {
      const r = rowTotals[m]
      if (!r) return acc
      return {
        inflow: Math.max(acc.inflow, Math.abs(r.inflow)),
        outflow: Math.max(acc.outflow, Math.abs(r.outflow)),
        net: Math.max(acc.net, Math.abs(r.net)),
      }
    },
    { inflow: 0, outflow: 0, net: 0 },
  )

  function barPct(value: number, max: number) {
    if (max === 0) return 0
    return Math.min(100, (Math.abs(value) / max) * 100)
  }

  function barColor(value: number) {
    if (value > 0) return 'bg-emerald-500/15 dark:bg-emerald-400/15'
    if (value < 0) return 'bg-destructive/15'
    return ''
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Category breakdown</CardTitle>
          <div className="flex gap-1">
            {(['1M', '3M', '6M', '1Y'] as Range[]).map((r) => (
              <button
                type="button"
                key={r}
                onClick={() => setRange(r)}
                className={`px-2 py-1 text-xs rounded font-medium transition-colors ${
                  range === r
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-muted/50 border-b">
                <th className="sticky left-0 z-10 bg-muted px-3 py-2 text-left font-medium text-muted-foreground">
                  Month
                </th>
                {categories.map((cat) => (
                  <th
                    key={cat}
                    className="px-3 py-2 text-right font-medium text-muted-foreground whitespace-nowrap"
                  >
                    {cat}
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                  Inflow
                </th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                  Outflow
                </th>
                <th className="sticky right-0 z-10 bg-muted px-3 py-2 text-right font-medium text-muted-foreground">
                  Net
                </th>
              </tr>
            </thead>
            <tbody>
              {monthsDescending.map((month) => {
                const row = rowTotals[month] ?? { inflow: 0, outflow: 0, net: 0 }
                const isExpandedMonth = activeCell?.month === month
                return (
                  <React.Fragment key={month}>
                    <tr
                      className={`border-b hover:bg-muted/30 ${isExpandedMonth ? 'bg-muted/40' : ''}`}
                      data-testid={`row-${month}`}
                    >
                      <th className="sticky left-0 z-10 bg-background px-3 py-2 text-left font-medium whitespace-nowrap">
                        {fmtMonth(month)}
                      </th>
                      {categories.map((cat) => {
                        const cell = cells[month]?.[cat]
                        const total = cell?.total ?? 0
                        const isOpen = activeCell?.month === month && activeCell.category === cat
                        return (
                          <td
                            key={cat}
                            className={`relative px-3 py-2 text-right tabular-nums cursor-pointer hover:bg-muted/40 ${
                              isOpen ? 'bg-muted/60 ring-1 ring-inset ring-border' : ''
                            } ${amountClass(total)}`}
                            onClick={() => cell && toggleCell(month, cat)}
                            data-testid={`cell-${month}-${cat}`}
                          >
                            {fmtMoney(total, { signed: true })}
                            {cell?.hasNeedsReview && (
                              <span
                                className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-amber-500"
                                aria-label="has needs-review transactions"
                              />
                            )}
                            {cell?.hasRecurring && (
                              <span
                                className="absolute bottom-0.5 right-1 text-sky-500 text-[10px] leading-none"
                                aria-label="has recurring transactions"
                              >
                                ↻
                              </span>
                            )}
                          </td>
                        )
                      })}
                      <td className={`relative px-3 py-2 text-right tabular-nums ${amountClass(row.inflow)}`}>
                        <span
                          aria-hidden
                          className={`absolute inset-y-1 left-1 rounded-sm ${barColor(row.inflow)}`}
                          style={{ width: `calc(${barPct(row.inflow, totalsMax.inflow)}% - 0.5rem)` }}
                        />
                        <span className="relative">{fmtMoney(row.inflow, { signed: true })}</span>
                      </td>
                      <td className={`relative px-3 py-2 text-right tabular-nums ${amountClass(row.outflow)}`}>
                        <span
                          aria-hidden
                          className={`absolute inset-y-1 left-1 rounded-sm ${barColor(row.outflow)}`}
                          style={{ width: `calc(${barPct(row.outflow, totalsMax.outflow)}% - 0.5rem)` }}
                        />
                        <span className="relative">{fmtMoney(row.outflow, { signed: true })}</span>
                      </td>
                      <td className={`relative sticky right-0 z-10 bg-muted px-3 py-2 text-right tabular-nums font-semibold ${amountClass(row.net)}`}>
                        <span
                          aria-hidden
                          className={`absolute inset-y-1 left-1 rounded-sm ${barColor(row.net)}`}
                          style={{ width: `calc(${barPct(row.net, totalsMax.net)}% - 0.5rem)` }}
                        />
                        <span className="relative">{fmtMoney(row.net, { signed: true })}</span>
                      </td>
                    </tr>
                    {isExpandedMonth && (
                      <tr className="border-b">
                        <td colSpan={categories.length + 4} className="p-0">
                          {(() => {
                            const cell = cells[month]?.[activeCell!.category]
                            if (!cell) return null
                            return (
                              <>
                                <div className="px-3 pt-2 pb-1 text-xs font-medium text-muted-foreground bg-muted/30">
                                  {activeCell!.category} · {fmtMonth(month)} ·{' '}
                                  <span className="font-normal">{cell.transactions.length} transaction{cell.transactions.length === 1 ? '' : 's'}</span>
                                </div>
                                <ExpandedTransactions
                                  transactions={cell.transactions}
                                  bindingByTxnId={breakdown.bindingByTxnId}
                                  ruleCountsInWindow={breakdown.ruleCountsInWindow}
                                />
                              </>
                            )
                          })()}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
              <tr className="border-t bg-muted/30 font-semibold">
                <th className="sticky left-0 z-10 bg-muted px-3 py-2 text-left">Total</th>
                {categories.map((cat) => (
                  <td key={cat} className={`px-3 py-2 text-right tabular-nums ${amountClass(colTotals[cat] ?? 0)}`}>
                    {fmtMoney(colTotals[cat] ?? 0, { signed: true })}
                  </td>
                ))}
                <td className={`px-3 py-2 text-right tabular-nums ${amountClass(grand.inflow)}`}>
                  {fmtMoney(grand.inflow, { signed: true })}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${amountClass(grand.outflow)}`}>
                  {fmtMoney(grand.outflow, { signed: true })}
                </td>
                <td className={`sticky right-0 z-10 bg-muted px-3 py-2 text-right tabular-nums ${amountClass(grand.net)}`}>
                  {fmtMoney(grand.net, { signed: true })}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
