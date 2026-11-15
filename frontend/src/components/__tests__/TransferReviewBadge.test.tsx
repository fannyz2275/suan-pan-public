import { act, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { fetchReview } from '@/lib/transfers'
import TransferReviewBadge from '../TransferReviewBadge'

vi.mock('@/lib/transfers', () => ({ fetchReview: vi.fn() }))

it('keeps a failed review visible until refresh succeeds', async () => {
  vi.mocked(fetchReview).mockRejectedValueOnce(new Error('offline'))
  const { rerender } = render(<TransferReviewBadge onClick={() => {}} refreshKey={0} />)
  expect(await screen.findByText('Transfer review unavailable')).toBeInTheDocument()

  let resolve!: (rows: Awaited<ReturnType<typeof fetchReview>>) => void
  vi.mocked(fetchReview).mockReturnValueOnce(new Promise(done => { resolve = done }))
  rerender(<TransferReviewBadge onClick={() => {}} refreshKey={1} />)
  expect(screen.getByText('Transfer review unavailable')).toBeInTheDocument()
  await act(async () => resolve([]))
  await waitFor(() => expect(screen.queryByRole('button')).not.toBeInTheDocument())
  expect(fetchReview).toHaveBeenLastCalledWith('all')
})
