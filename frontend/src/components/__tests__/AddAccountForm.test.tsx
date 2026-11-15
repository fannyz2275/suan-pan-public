import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AddAccountForm from '../AddAccountForm'
import { accountsApi } from '@/lib/api'
import type { Account } from '@/lib/types'

vi.mock('@/lib/api', () => ({
  accountsApi: {
    create: vi.fn(),
  },
}))

beforeEach(() => {
  vi.mocked(accountsApi.create).mockReset().mockResolvedValue({ id: 'new', type: 'checking', name: 'X', balance: 0 } as Account)
})

describe('AddAccountForm', () => {
  it('renders type select and name input', () => {
    render(<AddAccountForm onSaved={() => {}} onCancel={() => {}} />)
    expect(screen.getByLabelText(/type/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^name$/i)).toBeInTheDocument()
  })

  it('changes the visible per-type fields when type is changed', () => {
    render(<AddAccountForm onSaved={() => {}} onCancel={() => {}} />)
    expect(screen.getByLabelText(/balance/i)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/type/i), { target: { value: 'property' } })
    expect(screen.queryByLabelText(/^balance/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/estimated value/i)).toBeInTheDocument()
  })

  it('blocks submit with empty name', () => {
    const onSaved = vi.fn()
    render(<AddAccountForm onSaved={onSaved} onCancel={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /save account/i }))
    expect(accountsApi.create).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
    expect(screen.getByText(/name is required/i)).toBeInTheDocument()
  })

  it('blocks submit with invalid last4', () => {
    render(<AddAccountForm onSaved={() => {}} onCancel={() => {}} />)
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Chase' } })
    fireEvent.change(screen.getByLabelText(/last 4 digits/i), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: /save account/i }))
    expect(accountsApi.create).not.toHaveBeenCalled()
    expect(screen.getByText(/last 4 digits must be exactly 4 digits/i)).toBeInTheDocument()
  })

  it('valid submit calls create and triggers onSaved', async () => {
    const onSaved = vi.fn()
    render(<AddAccountForm onSaved={onSaved} onCancel={() => {}} />)
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Chase' } })
    fireEvent.change(screen.getByLabelText(/nickname/i), { target: { value: 'Joint' } })
    fireEvent.change(screen.getByLabelText(/last 4 digits/i), { target: { value: '7890' } })
    fireEvent.click(screen.getByRole('button', { name: /save account/i }))
    await waitFor(() => expect(accountsApi.create).toHaveBeenCalledTimes(1))
    expect(vi.mocked(accountsApi.create).mock.calls[0][0]).toMatchObject({
      type: 'checking',
      name: 'Chase',
      nickname: 'Joint',
      account_number_last4: '7890',
    })
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })
})
