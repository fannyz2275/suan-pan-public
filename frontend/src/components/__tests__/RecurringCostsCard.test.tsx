import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import RecurringCostsCard from '../RecurringCostsCard'
import { listRules, runDetection, patchRule, type RecurringRule } from '@/lib/recurring'

vi.mock('@/lib/recurring', () => ({ listRules: vi.fn(), runDetection: vi.fn(), patchRule: vi.fn() }))
const rule = { id: 'r', keyword: 'Internet', frequency: 'monthly', last_seen_date: '2026-09-04',
  status: 'auto_applied', direction: 'expense', amount_median: 60 } as RecurringRule
beforeEach(() => { vi.clearAllMocks(); vi.mocked(listRules).mockResolvedValue([rule]) })

it('shows clear frequency and the latest recorded payment', async () => {
  render(<RecurringCostsCard />)
  expect(await screen.findByText('Monthly')).toBeInTheDocument()
  expect(screen.getByText(/Last paid Sep 4, 2026/)).toBeInTheDocument()
  expect(screen.queryByText(/Typical amount per payment/)).not.toBeInTheDocument()
  expect(screen.getByLabelText('Hide payments last seen before')).toBeInTheDocument()
})

it('distinguishes bi-weekly from twice a month and handles unknown dates', async () => {
  vi.mocked(listRules).mockResolvedValue([
    { ...rule, frequency: 'biweekly', last_seen_date: null },
    { ...rule, id: 's', frequency: 'semi_monthly' }, { ...rule, id: 'a', frequency: 'annual' },
  ])
  render(<RecurringCostsCard />)
  expect(await screen.findByText('Bi-weekly')).toBeInTheDocument()
  expect(screen.getByText('Twice a month')).toBeInTheDocument()
  expect(screen.getByText('Annually')).toBeInTheDocument()
  expect(screen.getByText('Latest payment unavailable')).toBeInTheDocument()
})

it('recovers from a scan timeout without clearing saved rules', async () => {
  vi.mocked(runDetection).mockRejectedValue(Object.assign(new Error('timeout'), { code: 'ECONNABORTED' }))
  render(<RecurringCostsCard />)
  await screen.findByText('Internet')
  fireEvent.click(screen.getByRole('button', { name: 'Scan transactions' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/taking longer/)
  expect(screen.getByRole('alert')).not.toHaveTextContent('saved rules are unchanged')
  expect(screen.getByText('Internet')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Refresh results' })).toBeEnabled()
})

it('hides payments before the chosen month without hiding unknown dates', async () => {
  vi.mocked(listRules).mockResolvedValue([rule, { ...rule, id:'old', keyword:'Old service', last_seen_date:'2026-08-31' },
    { ...rule, id:'unknown', keyword:'Undated service', last_seen_date:null }])
  render(<RecurringCostsCard />)
  await screen.findByText('Old service')
  fireEvent.change(screen.getByLabelText('Hide payments last seen before'), {target:{value:'2026-09'}})
  expect(screen.queryByText('Old service')).not.toBeInTheDocument()
  expect(screen.getByText('Internet')).toBeInTheDocument()
  expect(screen.getByText('Undated service')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'Show all dates'}))
  expect(screen.getByText('Old service')).toBeInTheDocument()
})

it('does not promise unchanged server data after a failed scan', async () => {
  vi.mocked(runDetection).mockRejectedValue(new Error('server error'))
  render(<RecurringCostsCard />)
  await screen.findByText('Internet')
  fireEvent.click(screen.getByRole('button', { name: 'Scan transactions' }))
  expect(await screen.findByRole('alert')).toHaveTextContent("couldn't confirm")
  expect(screen.getByRole('alert')).not.toHaveTextContent('saved rules are unchanged')
  expect(screen.getByText('Internet')).toBeInTheDocument()
})

it('allows correcting and confirming the frequency inline', async () => {
  vi.mocked(patchRule).mockResolvedValue({...rule,frequency:'biweekly',status:'user_confirmed'})
  render(<RecurringCostsCard />)
  await screen.findByText('Internet')
  fireEvent.click(screen.getByRole('button',{name:'Change frequency for Internet'}))
  fireEvent.change(screen.getByLabelText('Frequency for Internet'), {target:{value:'biweekly'}})
  await waitFor(() => expect(screen.queryByLabelText('Frequency for Internet')).not.toBeInTheDocument())
  expect(screen.getByText('Bi-weekly')).toBeInTheDocument()
  expect(patchRule).toHaveBeenCalledWith('r',{action:'edit',frequency:'biweekly'})
})
