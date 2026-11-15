import type { Transaction } from './categoryBreakdown'
import api from './api'

export const localMonth = (today = new Date()) => `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`
const iso = (year: number, month: number, day: number) => `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
const excluded = new Set(['auto_paired', 'user_confirmed_internal', 'external'])

export async function fetchSummaryTransactions(signal: AbortSignal): Promise<Transaction[]> {
  const rows: Transaction[] = []
  const limit = 500
  for (let offset = 0; ; offset += limit) {
    const { data } = await api.get<Transaction[]>('/finance/transactions', {
      params: { limit, offset, exclude_transfers: true }, signal,
    })
    rows.push(...data)
    if (data.length < limit) return rows
  }
}

export function summarize(rows: Transaction[]) {
  const incomeCents = rows.reduce((sum, t) => sum + (t.amount > 0 ? Math.round(t.amount * 100) : 0), 0)
  const spendingCents = rows.reduce((sum, t) => sum + (t.amount < 0 ? -Math.round(t.amount * 100) : 0), 0)
  return {
    income: incomeCents / 100,
    spending: spendingCents / 100,
    kept: (incomeCents - spendingCents) / 100,
    rate: incomeCents > 0 ? (incomeCents - spendingCents) / incomeCents * 100 : null,
  }
}

export function spendingSummary(transactions: Transaction[], month: string, today = new Date()) {
  const [year, m] = month.split('-').map(Number)
  const previous = new Date(year, m - 2, 1)
  const py = previous.getFullYear(), pm = previous.getMonth() + 1
  const days = new Date(year, m, 0).getDate()
  const previousDays = new Date(py, pm, 0).getDate()
  const current = month === localMonth(today)
  const endDay = current ? today.getDate() : days
  // On March 31, compare March 1-28 with February 1-28, not 31 days with 28.
  const compareDay = current ? Math.min(endDay, previousDays) : days
  const from = iso(year, m, 1), to = iso(year, m, endDay)
  const compareTo = iso(year, m, compareDay)
  const previousFrom = iso(py, pm, 1), previousTo = iso(py, pm, current ? compareDay : previousDays)
  const eligible = transactions.filter(t => !excluded.has(t.transfer_status ?? ''))
  const within = (start: string, end: string) => eligible.filter(t => t.date >= start && t.date <= end)
  const rows = within(from, to)
  const comparisonRows = within(from, compareTo)
  const previousRows = within(previousFrom, previousTo)
  return { from, to, compareTo, previousFrom, previousTo, rows, comparisonRows, previousRows,
    totals: summarize(rows), comparison: summarize(comparisonRows), previous: summarize(previousRows),
    needsReview: rows.filter(t => t.transfer_status === 'needs_review').length,
  }
}
