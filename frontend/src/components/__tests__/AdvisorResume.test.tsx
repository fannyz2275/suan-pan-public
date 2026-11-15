import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import PendingAnalysis from '../PendingAnalysis'

it('requires a click to continue and disables continuation while busy', async () => {
  const resume = vi.fn()
  const pending = { id: 'p', ready: true, requirements: ['aligned_wealth'], missing: [], upload_action: null }
  const { rerender } = render(<PendingAnalysis pending={pending} busy={false} onContinue={resume} onUpload={vi.fn()} />)
  expect(resume).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Continue analysis' }))
  expect(resume).toHaveBeenCalledTimes(1)
  rerender(<PendingAnalysis pending={pending} busy onContinue={resume} onUpload={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Continue analysis' })).toBeDisabled()
})

it('partial data offers upload without a continuation call', () => {
  const resume = vi.fn()
  render(<PendingAnalysis pending={{ id:'p', ready:false, requirements:['aligned_wealth'], missing:['aligned_wealth'], upload_action:'upload_statements' }} busy={false} onContinue={resume} onUpload={vi.fn()} />)
  expect(screen.queryByRole('button', { name:'Continue analysis' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name:'Upload missing statements' })).toBeInTheDocument()
  expect(resume).not.toHaveBeenCalled()
})
