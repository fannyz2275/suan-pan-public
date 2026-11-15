import { describe, it, expect } from 'vitest'
import { applyGoalToSeries } from '@/lib/applyGoalToSeries'
import type { CashFlowPoint, Goal } from '@/lib/types'

const series: CashFlowPoint[] = [
  { month: '2026-04', balance: 10000 },
  { month: '2026-05', balance: 11000 },
  { month: '2026-06', balance: 12000 },
  { month: '2026-07', balance: 13000 },
  { month: '2026-08', balance: 14000 },
  { month: '2026-09', balance: 15000 },
]

const goal = (over: Partial<Goal>): Goal => ({
  id: 'g1', name: 'Wedding', type: 'life_event',
  target_amount: 5000, target_date: '2026-07-15',
  current_progress: 0, feasibility_score: null, status: 'active',
  ...over,
} as Goal)

describe('applyGoalToSeries', () => {
  it('subtracts target_amount at the goal month and all subsequent', () => {
    const out = applyGoalToSeries(series, goal({}))
    expect(out[0].balance).toBe(10000)
    expect(out[1].balance).toBe(11000)
    expect(out[2].balance).toBe(12000)
    expect(out[3].balance).toBe(13000 - 5000)
    expect(out[4].balance).toBe(14000 - 5000)
    expect(out[5].balance).toBe(15000 - 5000)
  })

  it('returns the original series unchanged when target month is before the series', () => {
    const earlyGoal = goal({ target_date: '2025-12-31' })
    const out = applyGoalToSeries(series, earlyGoal)
    expect(out).toEqual(series)
  })

  it('returns the original series unchanged when target month is after the series', () => {
    const lateGoal = goal({ target_date: '2027-01-15' })
    const out = applyGoalToSeries(series, lateGoal)
    expect(out).toEqual(series)
  })

  it('does not mutate the input series', () => {
    const before = JSON.stringify(series)
    applyGoalToSeries(series, goal({}))
    expect(JSON.stringify(series)).toBe(before)
  })
})
