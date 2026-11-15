import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import Login from '@/pages/Login'
import ForgotPassword from '@/pages/ForgotPassword'
import ResetPassword from '@/pages/ResetPassword'
import { supabase } from '@/lib/supabase'

vi.mock('@/lib/supabase', () => ({ supabase: { auth: {
  resetPasswordForEmail: vi.fn(), getSession: vi.fn(), updateUser: vi.fn(), signOut: vi.fn(),
} } }))
beforeEach(() => { vi.resetAllMocks(); window.history.replaceState({}, '', '/') })

it('offers password recovery from login', () => {
  render(<MemoryRouter><Login /></MemoryRouter>)
  expect(screen.getByRole('link', { name: 'Forgot password?' })).toHaveAttribute('href', '/forgot-password')
})

it('requests a reset email using the current origin', async () => {
  vi.mocked(supabase.auth.resetPasswordForEmail).mockResolvedValue({ data: {}, error: null })
  render(<MemoryRouter><ForgotPassword /></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'person@example.com' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
  expect(await screen.findByRole('status')).toHaveTextContent('If an account exists')
  expect(supabase.auth.resetPasswordForEmail).toHaveBeenCalledWith('person@example.com', { redirectTo: `${window.location.origin}/reset-password` })
})

it('allows retry after a reset-email network error', async () => {
  vi.mocked(supabase.auth.resetPasswordForEmail).mockRejectedValue(new Error('offline'))
  render(<MemoryRouter><ForgotPassword /></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'person@example.com' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not send')
  expect(screen.getByRole('button', { name: 'Send reset link' })).toBeEnabled()
})

it('does not offer password entry without a recovery session', async () => {
  vi.mocked(supabase.auth.getSession).mockResolvedValue({ data: { session: null }, error: null })
  render(<MemoryRouter><ResetPassword /></MemoryRouter>)
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid or has expired')
  expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
})

const validSession = () => {
  vi.mocked(supabase.auth.getSession).mockResolvedValue({ data: { session: { access_token: 'test', refresh_token: 'test', token_type: 'bearer', expires_in: 3600, user: { id: 'test', app_metadata: {}, user_metadata: {}, aud: 'authenticated', created_at: '' } } }, error: null })
}

it('rejects mismatched passwords, then saves a matching password', async () => {
  validSession()
  vi.mocked(supabase.auth.updateUser).mockResolvedValue({ data: { user: null }, error: null } as unknown as Awaited<ReturnType<typeof supabase.auth.updateUser>>)
  vi.mocked(supabase.auth.signOut).mockResolvedValue({ error: null })
  render(<MemoryRouter><ResetPassword /></MemoryRouter>)
  fireEvent.change(await screen.findByLabelText('New password'), { target: { value: 'new-password-123' } })
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'different-123' } })
  fireEvent.click(screen.getByRole('button', { name: 'Update password' }))
  expect(screen.getByRole('alert')).toHaveTextContent('do not match')
  expect(supabase.auth.updateUser).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'new-password-123' } })
  fireEvent.click(screen.getByRole('button', { name: 'Update password' }))
  expect(await screen.findByRole('status')).toHaveTextContent('password has been updated')
  expect(supabase.auth.updateUser).toHaveBeenCalledWith({ password: 'new-password-123' })
})

it('rejects an expired link even when another session exists', async () => {
  validSession()
  window.history.replaceState({}, '', '/reset-password#error_code=otp_expired')
  render(<MemoryRouter><ResetPassword /></MemoryRouter>)
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid or has expired')
})
