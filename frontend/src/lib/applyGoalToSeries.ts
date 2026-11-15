import type { CashFlowPoint, Goal } from './types'

/** Returns a new series where balance at the goal's target month and all
 * subsequent months has `goal.target_amount` subtracted. If the target month
 * is outside the series range, returns a shallow copy of the input. */
export function applyGoalToSeries(series: CashFlowPoint[], goal: Goal): CashFlowPoint[] {
  const targetMonth = goal.target_date.slice(0, 7) // "YYYY-MM"
  const targetIdx = series.findIndex((p) => p.month === targetMonth)
  if (targetIdx === -1) return series.map((p) => ({ ...p }))
  return series.map((p, i) =>
    i >= targetIdx ? { ...p, balance: p.balance - goal.target_amount } : { ...p }
  )
}
