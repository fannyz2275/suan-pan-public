import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import WhatIfGoalToggle from '../WhatIfGoalToggle'
import type { Goal } from '@/lib/types'

const goal = (over: Partial<Goal>): Goal => ({
  id: 'g1', name: 'Wedding', type: 'life_event',
  target_amount: 5000, target_date: '2026-07-15',
  current_progress: 0, feasibility_score: null, status: 'active',
  ...over,
} as Goal)

describe('WhatIfGoalToggle', () => {
  it('renders one pill per goal', () => {
    const goals = [goal({ id: 'g1', name: 'Wedding' }), goal({ id: 'g2', name: 'Down payment' })]
    render(<WhatIfGoalToggle goals={goals} activeIds={[]} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: /wedding/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /down payment/i })).toBeInTheDocument()
  })

  it('clicking a pill toggles its active state', () => {
    const onChange = vi.fn()
    const goals = [goal({ id: 'g1', name: 'Wedding' })]
    render(<WhatIfGoalToggle goals={goals} activeIds={[]} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /wedding/i }))
    expect(onChange).toHaveBeenCalledWith(['g1'])
  })

  it('clicking an active pill removes it', () => {
    const onChange = vi.fn()
    const goals = [goal({ id: 'g1', name: 'Wedding' })]
    render(<WhatIfGoalToggle goals={goals} activeIds={['g1']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /wedding/i }))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('caps active selections at 3 — disables additional pills', () => {
    const goals = [
      goal({ id: 'g1', name: 'A' }), goal({ id: 'g2', name: 'B' }),
      goal({ id: 'g3', name: 'C' }), goal({ id: 'g4', name: 'D' }),
    ]
    render(<WhatIfGoalToggle goals={goals} activeIds={['g1', 'g2', 'g3']} onChange={() => {}} />)
    const dPill = screen.getByRole('button', { name: /^D$/i })
    expect(dPill).toBeDisabled()
  })

  it('Clear all calls onChange with empty array', () => {
    const onChange = vi.fn()
    const goals = [goal({ id: 'g1' })]
    render(<WhatIfGoalToggle goals={goals} activeIds={['g1']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /clear all/i }))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('renders nothing when no goals provided', () => {
    const { container } = render(<WhatIfGoalToggle goals={[]} activeIds={[]} onChange={() => {}} />)
    expect(container.firstChild).toBeNull()
  })
})
