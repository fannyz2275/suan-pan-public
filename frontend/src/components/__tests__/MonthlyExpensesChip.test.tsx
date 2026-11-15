import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import MonthlyExpensesChip from '../MonthlyExpensesChip'
import type { ExpenseStatistic } from '@/lib/api'

const stat = (over: Partial<ExpenseStatistic> = {}): ExpenseStatistic => ({
  value: 4200, source: 'computed', sample_size: 87, window_days: 90, ...over,
})

describe('MonthlyExpensesChip', () => {
  it('shows Statistics badge when statistic.source is computed', () => {
    render(<MonthlyExpensesChip statistic={stat()} />)
    expect(screen.getByText('Statistics')).toBeInTheDocument()
    expect(screen.getByText(/\$4,200/)).toBeInTheDocument()
  })

  it('shows Not set when statistic is insufficient_data', () => {
    render(
      <MonthlyExpensesChip
        statistic={stat({ value: null, source: 'insufficient_data', sample_size: 3 })}
      />,
    )
    expect(screen.getByText(/not set/i)).toBeInTheDocument()
  })

  it('shows Not set when statistic is null (fetch failed)', () => {
    render(<MonthlyExpensesChip statistic={null} />)
    expect(screen.getByText(/not set/i)).toBeInTheDocument()
  })

  it('Statistics badge tooltip mentions transactions and sample size', () => {
    render(<MonthlyExpensesChip statistic={stat({ sample_size: 87 })} />)
    const tip = screen.getByText('Statistics').closest('[title]')?.getAttribute('title') ?? ''
    expect(tip).toMatch(/87/)
    expect(tip).toMatch(/transaction/i)
  })
})
