import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import CashOutlook from '../CashOutlook'
import type { CashFlowResponse } from '@/lib/types'
const forecast = { income_expense_history_available: true, monthly_income: 2000, residual_monthly_expenses: 1000, category_baselines: [], expense_budget_warning: null,
  cashflow: [-100, 1500, 3000].map((balance, i) => ({ month: `2026-${10 + i}`, balance, monthly_net: 1000, fixed_inflow: 0, fixed_outflow: 0, vesting_income: 0 })) } as CashFlowResponse
it('shows cash coverage and catches an early shortfall despite a positive ending balance', () => {
  render(<CashOutlook cash={2000} forecast={forecast} monthlyExpenses={1000} />)
  expect(screen.getByText(/could cover about 2.0 months/)).toBeInTheDocument()
  expect(screen.getByText('$3,000', { exact: true })).toBeInTheDocument()
  expect(screen.getByText(/Cash could fall below zero in 2026-10/)).toBeInTheDocument()
  expect(screen.getByText('Forecast assumptions').closest('details')).not.toHaveAttribute('open')
})
it('does not turn missing or zero expenses into infinite coverage or a reliable forecast', () => {
  render(<CashOutlook cash={2000} forecast={{ ...forecast, income_expense_history_available: false }} monthlyExpenses={0} />)
  expect(screen.getByText(/Not enough spending history/)).toBeInTheDocument()
  expect(screen.queryByText(/could cover about/)).not.toBeInTheDocument()
  expect(screen.queryByText(/\$3,000/)).not.toBeInTheDocument()
})
