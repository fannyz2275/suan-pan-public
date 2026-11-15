import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import api from '@/lib/api'
import { confirmStatements, detectStatements } from '@/lib/imports'
import UnifiedImportModal from '../UnifiedImportModal'

vi.mock('@/lib/api', () => ({ default: { get: vi.fn() }, accountsApi: { create: vi.fn() } }))
vi.mock('@/lib/imports', () => ({ confirmStatements: vi.fn(), detectStatements: vi.fn(), previewStatements: vi.fn() }))
vi.mock('../../contexts/ImportToastContext', () => ({ useImportToast: () => ({ showImportToast: vi.fn() }) }))
vi.mock('../PlaidConnectButton', () => ({ default: () => null }))
const account = { id: 'checking', name: 'My Checking', type: 'checking' }
beforeEach(() => vi.resetAllMocks())

it('saves only cash outside holdings and leaves investment transactions unchanged', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: [{ ...account, type: 'brokerage' }] })
  const transactions = [{ date: '2026-10-01', type: 'buy', amount: -10000 }]
  vi.mocked(detectStatements).mockResolvedValue({ groups: [{
    row_id: 'r', account_id: account.id, account_name: account.name, account_type: 'brokerage',
    kind: 'investment', error: null, preview: {
      statement_date: '2026-10-01', cash_value: 24902.21, total_value_reported: 206725.26,
      holdings: [{ ticker: 'CASH', quantity: 24902.21, price: 1, market_value: 24902.21 },
        { ticker: 'VTI', quantity: 1, price: 181823.05, market_value: 181823.05 }],
      investment_transactions: transactions,
    },
  }] })
  vi.mocked(confirmStatements).mockResolvedValue({ ok: true, saved: [], transfer_candidates_added: 0 })
  render(<UnifiedImportModal onClose={vi.fn()} onImported={vi.fn()} onRequestReview={vi.fn()} />)
  fireEvent.click(screen.getByRole('checkbox', { name: 'This file contains multiple accounts' }))
  await vi.waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  fireEvent.change(screen.getByTestId('unified-row-files'), { target: { files: [new File(['statement'], 'statement.txt')] } })
  fireEvent.click(screen.getByTestId('unified-preview-btn'))
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Confirm this account destination' }))
  fireEvent.click(screen.getByRole('button', { name: 'Preview statements' }))
  expect(screen.getByTestId('tie-out-banner')).toHaveTextContent('$231,627.47')
  fireEvent.change(screen.getByLabelText('Cash outside holdings'), { target: { value: '0' } })
  expect(screen.getByTestId('tie-out-match')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save all' }))
  await vi.waitFor(() => expect(confirmStatements).toHaveBeenCalledOnce())
  expect(vi.mocked(confirmStatements).mock.calls[0][0][0]).toMatchObject({ cash_value: 0, investment_transactions: transactions })
})

it('shows account loading failure and retries without closing the dialog', async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error('Network Error')).mockResolvedValueOnce({ data: [account] })
  render(<UnifiedImportModal onClose={vi.fn()} onImported={vi.fn()} onRequestReview={vi.fn()} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load accounts')
  fireEvent.click(screen.getByRole('button', { name: 'Retry accounts' }))
  await vi.waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(api.get).toHaveBeenCalledTimes(2)
})

it('detects accounts after upload and requires confirmation before preview/save', async () => {
  vi.mocked(api.get).mockResolvedValue({ data: [account] })
  vi.mocked(detectStatements).mockResolvedValue({ groups: [{
    row_id: 'r1', account_id: account.id, account_name: account.name, account_type: account.type,
    kind: 'bank', error: null, preview: { balance: 100, statement_date: '2026-10-01', transactions: [] },
  }] })
  vi.mocked(confirmStatements).mockResolvedValue({ ok: true, saved: [], transfer_candidates_added: 0 })
  const onImported = vi.fn()
  render(<UnifiedImportModal onClose={vi.fn()} onImported={onImported} onRequestReview={vi.fn()} />)
  fireEvent.click(screen.getByRole('checkbox', { name: 'This file contains multiple accounts' }))
  await vi.waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  fireEvent.change(screen.getByTestId('unified-row-files'), { target: {
    files: [new File(['date,amount\n2026-10-01,100'], 'statement.csv', { type: 'text/csv' })],
  } })
  fireEvent.click(screen.getByTestId('unified-preview-btn'))
  expect(await screen.findByRole('button', { name: 'Preview statements' })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Confirm this account destination' }))
  fireEvent.click(screen.getByRole('button', { name: 'Preview statements' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Save all' }))
  await vi.waitFor(() => expect(onImported).toHaveBeenCalledOnce())
})
