import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import api from '@/lib/api'
import RecordedRecurring from '../RecordedRecurring'
import { spendingSummary } from '@/lib/spendingSummary'

vi.mock('@/lib/api', () => ({ default: { get: vi.fn() } }))

it('shows only matched expenses from the selected period', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { bindings: [
    { transaction_id: '1', rule_id: 'r', rule_keyword: 'Internet', rule_frequency: 'monthly' },
    { transaction_id: '2', rule_id: 'r', rule_keyword: 'Internet', rule_frequency: 'monthly' },
  ] } })
  const result = spendingSummary([
    { id: '1', date: '2020-02-01', amount: -60, category: 'Bills', description: 'Internet bill' },
    { id: '2', date: '2020-01-01', amount: -60, category: 'Bills', description: 'Previous bill' },
  ], '2020-02')
  render(<RecordedRecurring result={result} />)
  expect(await screen.findByText('Internet bill')).toBeInTheDocument()
  expect(screen.queryByText('Previous bill')).not.toBeInTheDocument()
  expect(api.get).toHaveBeenCalledWith('/engine/recurring/match', expect.objectContaining({ params: { date_from: '2020-02-01', date_to: '2020-02-29' } }))
})

it('does not mistake a failed match request for no recurring charges', async () => {
  vi.mocked(api.get).mockRejectedValue(new Error('offline'))
  render(<RecordedRecurring result={spendingSummary([], '2020-02')} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load recurring matches')
})
