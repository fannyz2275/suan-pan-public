import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { usePlaidLink } from 'react-plaid-link'
import api from '@/lib/api'
import PlaidConnectButton from '../PlaidConnectButton'

vi.mock('@/lib/api', () => ({ default: { post: vi.fn() } }))
vi.mock('react-plaid-link', () => ({ usePlaidLink: vi.fn() }))
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.post).mockResolvedValue({ data: { link_token: 'test-token' } })
  vi.mocked(usePlaidLink).mockReturnValue({ ready: false, error: null, open: vi.fn(), exit: vi.fn(), submit: vi.fn() })
})
afterEach(() => vi.useRealTimers())

it('warns about sandbox before opening Plaid and allows cancellation', async () => {
  const open = vi.fn()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  vi.mocked(api.post).mockResolvedValue({ data: { link_token: 'test-token', environment: 'sandbox' } })
  vi.mocked(usePlaidLink).mockReturnValue({ ready: true, error: null, open, exit: vi.fn(), submit: vi.fn() })
  render(<PlaidConnectButton onConnected={vi.fn()} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Connect Bank' }))
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Sandbox'))
  expect(open).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Connect Bank' }))
  expect(open).toHaveBeenCalledTimes(1)
  confirm.mockRestore()
})

it('does not show a sandbox notice for production', async () => {
  const open = vi.fn()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.mocked(api.post).mockResolvedValue({ data: { link_token: 'live-token', environment: 'production' } })
  vi.mocked(usePlaidLink).mockReturnValue({ ready: true, error: null, open, exit: vi.fn(), submit: vi.fn() })
  render(<PlaidConnectButton onConnected={vi.fn()} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Connect Bank' }))
  expect(confirm).not.toHaveBeenCalled()
  expect(open).toHaveBeenCalledTimes(1)
  confirm.mockRestore()
})

it('can show the sandbox notice before Plaid is ready', async () => {
  const alert = vi.spyOn(window, 'alert').mockImplementation(() => {})
  vi.mocked(api.post).mockResolvedValue({ data: { link_token: 'test-token', environment: 'sandbox' } })
  render(<PlaidConnectButton onConnected={vi.fn()} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'Connect Bank' }))
  expect(alert).toHaveBeenCalledWith(expect.stringContaining('Sandbox'))
  alert.mockRestore()
})

it('times out a stalled initialization and offers retry', async () => {
  vi.useFakeTimers()
  render(<PlaidConnectButton onConnected={vi.fn()} />)
  await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
  expect(screen.getByRole('alert')).toHaveTextContent('taking too long')
  fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
  await act(async () => {})
  expect(api.post).toHaveBeenCalledTimes(2)
})

it('surfaces a Plaid script error instead of leaving a disabled button', async () => {
  vi.mocked(usePlaidLink).mockReturnValue({ ready: false, error: new ErrorEvent('error'), open: vi.fn(), exit: vi.fn(), submit: vi.fn() })
  render(<PlaidConnectButton onConnected={vi.fn()} />)
  await act(async () => {})
  expect(screen.getByRole('alert')).toHaveTextContent('could not load')
})

it('handles errors when the Plaid window exits', async () => {
  render(<PlaidConnectButton onConnected={vi.fn()} />)
  await act(async () => {})
  const options = vi.mocked(usePlaidLink).mock.calls.at(-1)![0]
  expect(options.onExit).toBeTypeOf('function')
  act(() => options.onExit?.({ error_code: 'INVALID_LINK_TOKEN', error_type: 'INVALID_INPUT', error_message: '', display_message: '' }, { institution: null, status: null, link_session_id: '', request_id: '' }))
  expect(screen.getByRole('alert')).toHaveTextContent('closed with an error')
})
