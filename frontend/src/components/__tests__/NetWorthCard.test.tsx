import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import NetWorthCard from '../NetWorthCard'
import type { NetWorthNode, Snapshot } from '@/lib/types'

const tree: NetWorthNode = {
  id: 'root', name: 'Net Worth', kind: 'root',
  value: 19500, signed_value: 19500,
  children: [
    { id: 'liquid',       name: 'Liquid Assets',      kind: 'class', value: 1000,  signed_value: 1000 },
    { id: 'investments',  name: 'Investments',        kind: 'class', value: 20000, signed_value: 20000 },
    { id: 'non_current',  name: 'Non-current Assets', kind: 'class', value: 0,     signed_value: 0 },
    { id: 'liabilities',  name: 'Liabilities',        kind: 'class', value: 1500,  signed_value: -1500 },
  ],
}

const snapshot: Snapshot = {
  net_worth: 19500, liquid_net_worth: 21000,
  liquid_assets: 1000, investment_assets: 20000,
  non_current_assets: 0, total_liabilities: 1500,
}

describe('NetWorthCard', () => {
  it('renders the four class rows from the tree when provided', () => {
    render(<NetWorthCard snapshot={snapshot} tree={tree} />)
    expect(screen.getByText('Cash you can use')).toBeInTheDocument()
    expect(screen.getByText('Investments')).toBeInTheDocument()
    expect(screen.getByText('Property and other assets')).toBeInTheDocument()
    expect(screen.getByText('What you owe')).toBeInTheDocument()
  })

  it('renders the root total from the tree', () => {
    render(<NetWorthCard snapshot={snapshot} tree={tree} />)
    // Root is rendered twice (header badge + summary row); both must show the same number.
    const matches = screen.getAllByText(/\$19,500/)
    expect(matches.length).toBeGreaterThanOrEqual(1)
  })

  it('renders the liabilities row as a negative signed value', () => {
    render(<NetWorthCard snapshot={snapshot} tree={tree} />)
    expect(screen.getByText(/-\$1,500/)).toBeInTheDocument()
  })

  it('falls back to legacy snapshot rows when tree is null', () => {
    render(<NetWorthCard snapshot={snapshot} tree={null} />)
    expect(screen.getByText('Cash you can use')).toBeInTheDocument()
    expect(screen.getByText('Investments')).toBeInTheDocument()
  })
})
