import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import CashFlowExplainer from '../CashFlowExplainer'
import { requestCashFlowExplanation } from '@/lib/api'
import type { CashFlowExplainPayload } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  requestCashFlowExplanation: vi.fn(),
}))

const payload: CashFlowExplainPayload = {
  projection: [{ month: '2026-05', balance: 8500 }],
  history: [{ month: '2026-04', balance: 8200 }],
  starting_balance: 8200,
  monthly_income: 6000,
  monthly_expenses: 4500,
  vesting_events: [],
  fixed_recurring: { inflow: 0, outflow: 0 },
}

beforeEach(() => {
  vi.mocked(requestCashFlowExplanation).mockReset().mockResolvedValue('A short explanation.')
})

describe('CashFlowExplainer', () => {
  it('initially renders the link, not the explanation', () => {
    render(<CashFlowExplainer payload={payload} refreshKey={0} />)
    expect(screen.getByRole('button', { name: /how is this calculated/i })).toBeInTheDocument()
    expect(screen.queryByText(/a short explanation/i)).not.toBeInTheDocument()
  })

  it('clicking the link fetches and shows the explanation', async () => {
    render(<CashFlowExplainer payload={payload} refreshKey={0} />)
    fireEvent.click(screen.getByRole('button', { name: /how is this calculated/i }))
    await waitFor(() => expect(screen.getByText(/a short explanation/i)).toBeInTheDocument())
    expect(requestCashFlowExplanation).toHaveBeenCalledTimes(1)
  })

  it('reuses cached explanation on a second render with the same refreshKey', async () => {
    const { rerender } = render(<CashFlowExplainer payload={payload} refreshKey={0} />)
    fireEvent.click(screen.getByRole('button', { name: /how is this calculated/i }))
    await waitFor(() => expect(screen.getByText(/a short explanation/i)).toBeInTheDocument())
    rerender(<CashFlowExplainer payload={payload} refreshKey={0} />)
    expect(requestCashFlowExplanation).toHaveBeenCalledTimes(1)
  })

  it('invalidates cache when refreshKey changes', async () => {
    const { rerender } = render(<CashFlowExplainer payload={payload} refreshKey={0} />)
    fireEvent.click(screen.getByRole('button', { name: /how is this calculated/i }))
    await waitFor(() => expect(requestCashFlowExplanation).toHaveBeenCalledTimes(1))
    rerender(<CashFlowExplainer payload={payload} refreshKey={1} />)
    expect(screen.getByRole('button', { name: /how is this calculated/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /how is this calculated/i }))
    await waitFor(() => expect(requestCashFlowExplanation).toHaveBeenCalledTimes(2))
  })
})
