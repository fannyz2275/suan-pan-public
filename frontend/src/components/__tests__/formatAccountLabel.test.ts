import { describe, it, expect } from 'vitest'
import { formatAccountLabel } from '@/lib/formatAccountLabel'

describe('formatAccountLabel', () => {
  it('uses nickname over name when both are present', () => {
    expect(formatAccountLabel({ name: 'Chase Total Checking', nickname: 'Joint', account_number_last4: '7890' })).toBe('Joint (*7890)')
  })

  it('falls back to name when no nickname', () => {
    expect(formatAccountLabel({ name: 'Marcus Savings', account_number_last4: '0103' })).toBe('Marcus Savings (*0103)')
  })

  it('omits the suffix when account_number_last4 is missing', () => {
    expect(formatAccountLabel({ name: 'Property' })).toBe('Property')
  })

  it('omits the suffix when account_number_last4 is invalid (not 4 digits)', () => {
    expect(formatAccountLabel({ name: 'Petty Cash', account_number_last4: '12' })).toBe('Petty Cash')
    expect(formatAccountLabel({ name: 'Petty Cash', account_number_last4: 'abcd' })).toBe('Petty Cash')
  })

  it('returns "(unnamed)" when both nickname and name are missing', () => {
    expect(formatAccountLabel({})).toBe('(unnamed)')
    expect(formatAccountLabel({ account_number_last4: '9999' })).toBe('(unnamed) (*9999)')
  })

  it('parity with backend: same 5 fixtures the backend test uses', () => {
    expect(formatAccountLabel({ name: 'Chase Total Checking', nickname: 'Joint', account_number_last4: '7890' })).toBe('Joint (*7890)')
    expect(formatAccountLabel({ name: 'Marcus Savings', account_number_last4: '0103' })).toBe('Marcus Savings (*0103)')
    expect(formatAccountLabel({ name: 'Property' })).toBe('Property')
    expect(formatAccountLabel({ name: 'Petty Cash', account_number_last4: '12' })).toBe('Petty Cash')
    expect(formatAccountLabel({})).toBe('(unnamed)')
  })
})
