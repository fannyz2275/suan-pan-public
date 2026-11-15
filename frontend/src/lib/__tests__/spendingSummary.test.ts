import { describe, expect, it, vi } from 'vitest'
import { fetchSummaryTransactions, spendingSummary } from '../spendingSummary'
import api from '../api'
import type { Transaction } from '../categoryBreakdown'

vi.mock('../api', () => ({ default: { get: vi.fn() } }))
const row = (id: string, date: string, amount: number, transfer_status: string | null = null): Transaction => ({ id, date, amount, transfer_status, category: null })

describe('spending summary', () => {
  it('does not label category-only transfers as pending review', () => {
    const r = spendingSummary([{ ...row('1', '2026-09-01', -25), category: 'transfer' },
      { ...row('2', '2026-09-02', -50, 'dismissed'), category: 'transfer' }], '2026-09', new Date(2026, 9, 10))
    expect(r.needsReview).toBe(0)
    expect(r.totals.spending).toBe(75)
  })
  it('excludes recognized transfers, keeps dismissed and pending rows, and reconciles cents', () => {
    const r = spendingSummary([
      row('1', '2026-09-01', 1000), row('2', '2026-09-02', -100.11),
      row('3', '2026-09-03', -200, 'dismissed'), row('4', '2026-09-04', -50, 'needs_review'),
      row('5', '2026-09-05', 500, 'auto_paired'), row('6', '2026-09-06', -500, 'user_confirmed_internal'),
      row('7', '2026-09-07', -500, 'external'),
    ], '2026-09', new Date(2026, 9, 10))
    expect(r.totals.income).toBe(1000)
    expect(r.totals.spending).toBe(350.11)
    expect(r.totals.kept).toBe(649.89)
    expect(r.totals.rate).toBeCloseTo(64.989)
    expect(r.needsReview).toBe(1)
  })
  it('uses equal elapsed days across February and March while keeping current totals', () => {
    const r = spendingSummary([row('1', '2026-03-31', 500), row('2', '2026-03-28', 100), row('3', '2026-02-28', 50)], '2026-03', new Date(2026, 2, 31))
    expect(r.totals.income).toBe(600)
    expect(r.comparison.income).toBe(100)
    expect(r.previous.income).toBe(50)
    expect(r.compareTo).toBe('2026-03-28')
  })
  it('compares complete months across year boundaries', () => {
    const r = spendingSummary([], '2026-01', new Date(2026, 9, 10))
    expect(r.to).toBe('2026-01-31')
    expect(r.previousFrom).toBe('2025-12-01')
    expect(r.previousTo).toBe('2025-12-31')
    expect(r.totals.rate).toBeNull()
  })
  it('excludes future transactions and permits negative savings', () => {
    const r = spendingSummary([row('1', '2026-10-01', 100), row('2', '2026-10-02', -200), row('3', '2026-10-11', 500)], '2026-10', new Date(2026, 9, 10))
    expect(r.totals.kept).toBe(-100)
    expect(r.totals.rate).toBe(-100)
  })
  it('loads beyond the first page', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: Array.from({ length: 500 }, (_, i) => row(String(i), '2026-10-01', 1)) }).mockResolvedValueOnce({ data: [row('last', '2026-09-01', 2)] })
    const signal = new AbortController().signal
    expect(await fetchSummaryTransactions(signal)).toHaveLength(501)
    expect(api.get).toHaveBeenLastCalledWith('/finance/transactions', { params: { limit: 500, offset: 500, exclude_transfers: true }, signal })
  })
})
