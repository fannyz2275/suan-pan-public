import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import BulkRecategorizeConfirmCard from '../BulkRecategorizeConfirmCard'

const preview = {
  mode: 'preview' as const,
  matched: [
    { id: 't1', date: '2025-12-03', description: 'Amazon', amount: -42.18, old_category: 'Other' },
    { id: 't2', date: '2025-12-10', description: 'Amazon Prime', amount: -139, old_category: 'Other' },
  ],
  new_category: 'Shopping',
  updated_count: 0,
  failed_ids: [],
}

describe('BulkRecategorizeConfirmCard', () => {
  it('renders summary and matched rows', () => {
    render(<BulkRecategorizeConfirmCard preview={preview} onConfirm={() => {}} onCancel={() => {}} />)
    expect(screen.getByText(/apply category 'shopping' to 2 txns/i)).toBeInTheDocument()
    expect(screen.getByText(/amazon prime/i)).toBeInTheDocument()
  })

  it('calls onConfirm when Confirm clicked', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    render(<BulkRecategorizeConfirmCard preview={preview} onConfirm={onConfirm} onCancel={() => {}} />)
    await user.click(screen.getByRole('button', { name: /confirm/i }))
    expect(onConfirm).toHaveBeenCalled()
  })

  it('calls onCancel when Cancel clicked', async () => {
    const onCancel = vi.fn()
    const user = userEvent.setup()
    render(<BulkRecategorizeConfirmCard preview={preview} onConfirm={() => {}} onCancel={onCancel} />)
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()
  })

  it('does not call onConfirm when disabled', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const user = userEvent.setup()
    render(
      <BulkRecategorizeConfirmCard
        preview={preview}
        onConfirm={onConfirm}
        onCancel={onCancel}
        disabled={true}
      />,
    )
    await user.click(screen.getByRole('button', { name: /confirm/i }))
    expect(onConfirm).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(onCancel).not.toHaveBeenCalled()
  })
})
