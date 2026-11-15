import { useMemo, useState } from 'react'
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceDot,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCompactCurrency, formatCurrency } from '@/lib/formatters'
import { useCashFlowSeries } from '@/lib/useCashFlowSeries'
import { applyGoalToSeries } from '@/lib/applyGoalToSeries'
import WhatIfGoalToggle from './WhatIfGoalToggle'
import CashFlowExplainer from './CashFlowExplainer'
import type { CashFlowPoint, Goal } from '@/lib/types'
import type { CashFlowExplainPayload } from '@/lib/api'

interface Props {
  refreshKey?: number
  goals?: Goal[]
  startingBalance?: number
  monthlyIncome?: number
  monthlyExpenses?: number
}

const WHATIF_COLORS = ['#f59e0b', '#10b981', '#a855f7']

function formatMonth(ym: string): string {
  const [y, m] = ym.split('-')
  const d = new Date(Number(y), Number(m) - 1, 1)
  return d.toLocaleString('en-US', { month: 'short', year: '2-digit' })
}

export default function CashFlowChart({
  refreshKey = 0, goals = [],
  startingBalance = 0, monthlyIncome = 0, monthlyExpenses = 0,
}: Props) {
  const { series, todayIndex, loading } = useCashFlowSeries(refreshKey)
  const [activeGoalIds, setActiveGoalIds] = useState<string[]>([])

  const chartData = useMemo(() => {
    return series.map((p, i) => ({
      monthKey: p.month,
      month: formatMonth(p.month),
      balance: Math.round(p.balance),
      isProjected: i >= todayIndex,
    }))
  }, [series, todayIndex])

  const inRangeGoals = useMemo(() => {
    if (series.length === 0) return []
    const first = series[0].month
    const last = series[series.length - 1].month
    return goals.filter((g) => {
      const m = g.target_date.slice(0, 7)
      return m >= first && m <= last
    })
  }, [goals, series])

  const goalDots = useMemo(() => {
    return inRangeGoals
      .map((g) => {
        const monthKey = g.target_date.slice(0, 7)
        const point = chartData.find((d) => d.monthKey === monthKey)
        if (!point) return null
        return { goal: g, x: point.month, y: point.balance }
      })
      .filter((x): x is { goal: Goal; x: string; y: number } => x !== null)
  }, [inRangeGoals, chartData])

  const whatIfLines = useMemo(() => {
    return activeGoalIds
      .map((id, idx) => {
        const goal = inRangeGoals.find((g) => g.id === id)
        if (!goal) return null
        const projectedSlice: CashFlowPoint[] = series.slice(todayIndex)
        const adjusted = applyGoalToSeries(projectedSlice, goal)
        const dataKey = `whatif_${id}`
        const points = chartData.map((d, i) => ({
          ...d,
          [dataKey]: i >= todayIndex ? Math.round(adjusted[i - todayIndex].balance) : null,
        }))
        return { goal, dataKey, color: WHATIF_COLORS[idx % WHATIF_COLORS.length], points }
      })
      .filter((x): x is { goal: Goal; dataKey: string; color: string; points: typeof chartData } => x !== null)
  }, [activeGoalIds, inRangeGoals, series, chartData, todayIndex])

  const mergedData = useMemo(() => {
    if (whatIfLines.length === 0) return chartData
    return chartData.map((row, i) => {
      const merged: Record<string, unknown> = { ...row }
      whatIfLines.forEach((w) => {
        merged[w.dataKey] = w.points[i][w.dataKey as keyof typeof w.points[number]]
      })
      return merged as typeof row & Record<string, number | null>
    })
  }, [chartData, whatIfLines])

  const explainPayload: CashFlowExplainPayload = {
    projection: series.slice(todayIndex),
    history: series.slice(0, todayIndex),
    starting_balance: startingBalance,
    monthly_income: monthlyIncome,
    monthly_expenses: monthlyExpenses,
    vesting_events: [],
    fixed_recurring: { inflow: 0, outflow: 0 },
  }

  if (loading) return <Card><CardContent className="p-6 text-muted-foreground">Loading…</CardContent></Card>

  const todayMonthLabel = chartData[todayIndex]?.month

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Cash history and forecast</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={mergedData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="balanceGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => formatCompactCurrency(v)} />
            <Tooltip formatter={(v) => formatCurrency(Number(v))} />
            <Area
              type="monotone"
              dataKey="balance"
              stroke="#6366f1"
              fill="url(#balanceGrad)"
              strokeWidth={2}
              isAnimationActive={false}
            />
            {todayMonthLabel && (
              <ReferenceLine x={todayMonthLabel} stroke="#9ca3af" strokeDasharray="4 4" label={{ value: 'Today', fontSize: 10, fill: '#9ca3af', position: 'insideTopRight' }} />
            )}
            {goalDots.map(({ goal, x, y }) => (
              <ReferenceDot
                key={goal.id}
                x={x}
                y={y}
                r={5}
                fill="#f59e0b"
                stroke="#fff"
                strokeWidth={1.5}
                label={{ value: `${goal.name} (${formatCurrency(goal.target_amount)})`, fontSize: 10, fill: '#92400e', position: 'top' }}
              />
            ))}
            {whatIfLines.map((w) => (
              <Line
                key={w.dataKey}
                type="monotone"
                dataKey={w.dataKey}
                stroke={w.color}
                strokeDasharray="5 3"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>

        <WhatIfGoalToggle goals={inRangeGoals} activeIds={activeGoalIds} onChange={setActiveGoalIds} />
        <CashFlowExplainer payload={explainPayload} refreshKey={refreshKey} />
      </CardContent>
    </Card>
  )
}
