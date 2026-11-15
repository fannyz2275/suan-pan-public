import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AccountLeafEdit from '../AccountLeafEdit'
import { accountsApi } from '@/lib/api'
import type { Account } from '@/lib/types'

vi.mock('@/lib/api', () => ({
  accountsApi: {
    update: vi.fn(),
    remove: vi.fn(),
  },
}))

const baseAccount: Account = {
  id: 'a1', name: 'Chase Checking', type: 'checking', balance: 1000,
  nickname: null, account_number_last4: null,
} as Account

beforeEach(() => {
  vi.mocked(accountsApi.update).mockReset().mockResolvedValue({} as Account)
  vi.mocked(accountsApi.remove).mockReset().mockResolvedValue()
})

describe('AccountLeafEdit', () => {
  it('renders nickname and last-4 inputs', () => {
    render(<AccountLeafEdit account={baseAccount} onChanged={() => {}} onCancel={() => {}} />)
    expect(screen.getByLabelText(/nickname/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/last 4 digits/i)).toBeInTheDocument()
  })

  it('strips non-digits and truncates last-4 input to 4 chars', () => {
    render(<AccountLeafEdit account={baseAccount} onChanged={() => {}} onCancel={() => {}} />)
    const last4 = screen.getByLabelText(/last 4 digits/i) as HTMLInputElement
    fireEvent.change(last4, { target: { value: 'abcd1234567' } })
    expect(last4.value).toBe('1234')
  })

  it('save sends updated nickname and last4 in payload', async () => {
    const onChanged = vi.fn()
    render(<AccountLeafEdit account={baseAccount} onChanged={onChanged} onCancel={() => {}} />)
    fireEvent.change(screen.getByLabelText(/nickname/i), { target: { value: 'Joint' } })
    fireEvent.change(screen.getByLabelText(/last 4 digits/i), { target: { value: '7890' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(accountsApi.update).toHaveBeenCalledTimes(1))
    const call = vi.mocked(accountsApi.update).mock.calls[0]
    expect(call[0]).toBe('a1')
    expect(call[1]).toMatchObject({
      nickname: 'Joint',
      account_number_last4: '7890',
      name: 'Chase Checking',
    })
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('delete shows inline confirm; Yes calls remove + onChanged', async () => {
    const onChanged = vi.fn()
    render(<AccountLeafEdit account={baseAccount} onChanged={onChanged} onCancel={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    expect(screen.getByText(/delete this account\?/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /yes, delete/i }))
    await waitFor(() => expect(accountsApi.remove).toHaveBeenCalledWith('a1'))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('delete inline-confirm Cancel reverts to normal footer without removing', () => {
    render(<AccountLeafEdit account={baseAccount} onChanged={() => {}} onCancel={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }))
    expect(screen.getByRole('button', { name: /^save$/i })).toBeInTheDocument()
    expect(vi.mocked(accountsApi.remove)).not.toHaveBeenCalled()
  })
})
