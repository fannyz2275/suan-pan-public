import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import FinancialGrowth from '../FinancialGrowth'
import api from '@/lib/api'

vi.mock('@/lib/api', () => ({ default: { get: vi.fn() } }))
vi.mock('recharts', () => ({ ResponsiveContainer: () => null, LineChart: () => null, Line: () => null, XAxis: () => null, YAxis: () => null, CartesianGrid: () => null, Tooltip: () => null }))
beforeEach(() => vi.resetAllMocks())

it('shows unavailable growth instead of fabricating missing history or cost basis', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: {
    requested_start: '2026-07-10', baseline_date: null, as_of: '2026-10-10', account_count: 1,
    current: { cash: 100, investments: 0, other: 0, debt: 0, net_worth: 100 }, change: null, percent_change: null,
    changes: null, series: [], balance_dates: [],
    investments: { net_contributions: null, flow_count: 0, unrealized: { value: null, known_holdings: 0, total_holdings: 0, covered_accounts: 0, total_accounts: 0, oldest_date: null, latest_date: null }, prior_unrealized: null, unrealized_change: null },
  } })
  const { rerender } = render(<FinancialGrowth />)
  expect(await screen.findByText('Not enough complete account history to calculate growth.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '1Y' }))
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/engine/growth', expect.objectContaining({ params: { window: '1Y' } })))
  await screen.findByText('What you own minus what you owe')
  rerender(<FinancialGrowth refreshKey={1} />)
  await screen.findByText('What you own minus what you owe')
  expect(api.get).toHaveBeenCalledTimes(3)
})

it('shows endpoint errors and supports retry', async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ data: { account_count: 0 } })
  render(<FinancialGrowth />)
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByText('Add accounts to see financial growth.')).toBeInTheDocument()
})
