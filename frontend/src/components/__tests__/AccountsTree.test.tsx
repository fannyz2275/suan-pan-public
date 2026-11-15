import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import AccountsTree from '../AccountsTree'
import type { Account, NetWorthNode } from '@/lib/types'

vi.mock('@/lib/api', () => ({
  accountsApi: { update: vi.fn(), remove: vi.fn(), create: vi.fn() },
}))

const baseAccount = (over: Partial<Account>): Account => ({
  id: 'x', name: 'X', type: 'checking', balance: 0,
  nickname: null, account_number_last4: null,
  ...over,
} as Account)

const tree: NetWorthNode = {
  id: 'root', name: 'Net Worth', kind: 'root', value: 6400, signed_value: 6400,
  children: [
    {
      id: 'liquid', name: 'Liquid Assets', kind: 'class', value: 6400, signed_value: 6400,
      children: [
        {
          id: 'checking', name: 'Checking', kind: 'type', value: 6400, signed_value: 6400,
          children: [
            { id: 'a1', name: 'Chase (*7821)', kind: 'account', account_type: 'checking', value: 4200, signed_value: 4200 },
            { id: 'a2', name: 'BofA (*4412)',  kind: 'account', account_type: 'checking', value: 2200, signed_value: 2200 },
          ],
        },
      ],
    },
    { id: 'investments', name: 'Investments', kind: 'class', value: 0, signed_value: 0 },
    { id: 'non_current', name: 'Non-current Assets', kind: 'class', value: 0, signed_value: 0 },
    { id: 'liabilities', name: 'Liabilities', kind: 'class', value: 0, signed_value: 0 },
  ],
}

const accountsById: Record<string, Account> = {
  a1: baseAccount({ id: 'a1', name: 'Chase', account_number_last4: '7821' }),
  a2: baseAccount({ id: 'a2', name: 'BofA',  account_number_last4: '4412' }),
}

describe('AccountsTree', () => {
  it('renders the four class rows', () => {
    render(<AccountsTree tree={tree} accountsById={accountsById} onChanged={() => {}} />)
    expect(screen.getByText('Cash you can use')).toBeInTheDocument()
    expect(screen.getByText('Investments')).toBeInTheDocument()
    expect(screen.getByText('Property and other assets')).toBeInTheDocument()
    expect(screen.getByText('What you owe')).toBeInTheDocument()
  })

  it('class rows start expanded; type rows start collapsed', () => {
    render(<AccountsTree tree={tree} accountsById={accountsById} onChanged={() => {}} />)
    expect(screen.getByText('Checking')).toBeInTheDocument()
    expect(screen.queryByText('Chase (*7821)')).not.toBeInTheDocument()
  })

  it('clicking a type row reveals its account leaves', () => {
    render(<AccountsTree tree={tree} accountsById={accountsById} onChanged={() => {}} />)
    fireEvent.click(screen.getByText('Checking'))
    expect(screen.getByText('Chase (*7821)')).toBeInTheDocument()
    expect(screen.getByText('BofA (*4412)')).toBeInTheDocument()
  })

  it('clicking an account leaf opens the inline edit panel', () => {
    render(<AccountsTree tree={tree} accountsById={accountsById} onChanged={() => {}} />)
    fireEvent.click(screen.getByText('Checking'))
    fireEvent.click(screen.getByText('Chase (*7821)'))
    expect(screen.getByLabelText(/nickname/i)).toBeInTheDocument()
  })

  it('shows a loading placeholder when tree is null', () => {
    render(<AccountsTree tree={null} accountsById={{}} onChanged={() => {}} />)
    expect(screen.getByText(/loading accounts/i)).toBeInTheDocument()
  })

  it('renders Liabilities row in destructive color when signed_value < 0', () => {
    const negTree: NetWorthNode = {
      ...tree,
      children: tree.children!.map((c) =>
        c.id === 'liabilities'
          ? { ...c, value: 1500, signed_value: -1500 }
          : c
      ),
    }
    render(<AccountsTree tree={negTree} accountsById={accountsById} onChanged={() => {}} />)
    const row = screen.getByText(/-\$1,500/)
    expect(row.className).toMatch(/text-destructive/)
  })
})
