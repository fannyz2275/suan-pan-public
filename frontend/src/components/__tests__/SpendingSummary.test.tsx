import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import SpendingSummary from '../SpendingSummary'
import { fetchSummaryTransactions, localMonth } from '@/lib/spendingSummary'

vi.mock('@/lib/api', () => ({ default: { get: vi.fn() } }))
vi.mock('@/lib/spendingSummary', async importOriginal => ({ ...await importOriginal<typeof import('@/lib/spendingSummary')>(), fetchSummaryTransactions: vi.fn() }))
vi.mock('../RecordedRecurring', () => ({ default: () => null }))
beforeEach(() => vi.resetAllMocks())

it('explains the selected metric with summary data, not raw transactions', async () => {
  vi.mocked(fetchSummaryTransactions).mockResolvedValue([{ id: 'private-id', date: '2020-02-01', amount: -120, category: 'Food', description: 'Private merchant' }])
  const explain = vi.fn()
  render(<SpendingSummary onExplain={explain} />)
  await screen.findByRole('button', { name: /^Income/ })
  fireEvent.change(screen.getByLabelText('Summary month'), { target: { value: '2020-02' } })
  fireEvent.click(screen.getByRole('button', { name: 'Explain Spending' }))
  expect(explain).toHaveBeenCalledWith(expect.objectContaining({ label: 'Spending', prompt: expect.stringContaining('2020-02') }))
  const prompt = explain.mock.calls[0][0].prompt
  expect(prompt).toContain('120')
  expect(prompt).not.toContain('Private merchant')
  expect(prompt).not.toContain('private-id')
})

it('shares the selected month with category spending and excludes transfers', async () => {
  vi.mocked(fetchSummaryTransactions).mockResolvedValue([
    { id: 'a', date: '2020-02-01', amount: -120, category: 'Food', description: 'Groceries' },
    { id: 'b', date: '2020-01-01', amount: -80, category: 'Food', description: 'Old groceries' },
    { id: 'c', date: '2020-02-01', amount: -500, category: 'Food', transfer_status: 'external' },
  ])
  render(<SpendingSummary detailed />)
  await screen.findByRole('button', { name: /Income/ })
  fireEvent.change(screen.getByLabelText('Summary month'), { target: { value: '2020-02' } })
  const category = screen.getByRole('button', { name: /Food/ })
  expect(category).toHaveTextContent('$120')
  expect(category).toHaveTextContent('+$40')
  fireEvent.click(category)
  expect(screen.getByText('Groceries')).toBeInTheDocument()
  expect(screen.queryByText('Old groceries')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Summary month'), { target: { value: '2020-01' } })
  expect(screen.getByRole('button', { name: /Food/ })).toHaveTextContent('Comparison unavailable')
  expect(screen.queryByText('Groceries')).not.toBeInTheDocument()
})

it('expands the calculation and updates on month selection', async () => {
  const date = `${localMonth()}-01`
  vi.mocked(fetchSummaryTransactions).mockResolvedValue([{ id: '1', date, amount: 1000, category: 'income', description: 'Payroll' }])
  render(<SpendingSummary />)
  const income = await screen.findByRole('button', { name: /Income/ })
  fireEvent.click(income)
  expect(screen.getByText('Payroll')).toBeInTheDocument()
  expect(income).toHaveAttribute('aria-expanded', 'true')
  fireEvent.change(screen.getByLabelText('Summary month'), { target: { value: '2020-01' } })
  expect(screen.getByText(/No transactions for this period/)).toBeInTheDocument()
})

it('shows a failure instead of zero totals and retries', async () => {
  vi.mocked(fetchSummaryTransactions).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([])
  render(<SpendingSummary />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load')
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByText(/No transactions for this period/)).toBeInTheDocument()
})

it('refetches after a dashboard refresh', async () => {
  vi.mocked(fetchSummaryTransactions).mockResolvedValue([])
  const { rerender } = render(<SpendingSummary refreshKey={1} />)
  await screen.findByText(/No transactions for this period/)
  rerender(<SpendingSummary refreshKey={2} />)
  await screen.findByText(/No transactions for this period/)
  expect(fetchSummaryTransactions).toHaveBeenCalledTimes(2)
})
