import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import * as transfers from '@/lib/transfers'
import TransferReviewModal from '../TransferReviewModal'

vi.mock('@/lib/transfers', () => ({ fetchReview: vi.fn(), confirmPair: vi.fn(),
  markExternal: vi.fn(), dismiss: vi.fn(), linkTransactions: vi.fn() }))
const rows = ['a', 'b'].map((id) => ({ txn_id: id, date: '2026-10-01', description: id,
  amount: 100, account_name: id, transfer_status: 'auto_paired' as const,
  group_id: 'pair-1', suggested_match: null }))
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(transfers.fetchReview).mockResolvedValueOnce(rows).mockResolvedValue([])
  vi.mocked(transfers.confirmPair).mockResolvedValue(undefined)
})

it('confirms each pair once even when both sides are selected', async () => {
  render(<TransferReviewModal open onClose={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('checkbox', { name: /Select all/ }))
  fireEvent.click(screen.getByRole('button', { name: /Confirm auto-paired/ }))
  await screen.findByText(/Nothing to review/)
  expect(transfers.confirmPair).toHaveBeenCalledTimes(1)
})

it('shows refresh failures and releases busy state', async () => {
  vi.mocked(transfers.fetchReview).mockReset().mockResolvedValueOnce(rows).mockRejectedValueOnce(new Error('Refresh unavailable'))
  render(<TransferReviewModal open onClose={vi.fn()} onChanged={vi.fn()} />)
  fireEvent.click(await screen.findByRole('checkbox', { name: /Select all/ }))
  fireEvent.click(screen.getByRole('button', { name: /Confirm auto-paired/ }))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Refresh unavailable'))
  expect(screen.getByRole('button', { name: 'Retry loading' })).toBeEnabled()
})
