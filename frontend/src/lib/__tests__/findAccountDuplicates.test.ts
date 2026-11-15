import { describe, it, expect } from 'vitest'
import { findAccountDuplicates, normalizeName } from '../findAccountDuplicates'
import type { Account } from '../types'

const acct = (over: Partial<Account>): Account => ({
  id: over.id || crypto.randomUUID(),
  name: over.name ?? '',
  type: over.type ?? 'checking',
  balance: 0,
  nickname: null,
  account_number_last4: null,
  ...over,
} as Account)

describe('normalizeName', () => {
  it('lowercases, strips punctuation, collapses whitespace', () => {
    expect(normalizeName('Chase Checking')).toBe('chase checking')
    expect(normalizeName('  Chase   Checking  ')).toBe('chase checking')
    expect(normalizeName('Chase-Checking')).toBe('chase checking')
  })
  it('returns empty string for nullish input', () => {
    expect(normalizeName(null)).toBe('')
    expect(normalizeName(undefined)).toBe('')
  })
})

describe('findAccountDuplicates', () => {
  it('groups accounts that share type and last4', () => {
    const a = acct({ id: 'a', name: 'Chase Checking', account_number_last4: '1234' })
    const b = acct({ id: 'b', name: 'Different Name', account_number_last4: '1234' })
    const c = acct({ id: 'c', name: 'Chase Checking', account_number_last4: '5678' })
    const groups = findAccountDuplicates([a, b, c])
    expect(groups).toHaveLength(1)
    expect(groups[0].accounts.map((x) => x.id).sort()).toEqual(['a', 'b'])
  })

  it('groups same-type accounts without last4 by normalized name', () => {
    const a = acct({ id: 'a', name: 'Chase Checking' })
    const b = acct({ id: 'b', name: 'chase  checking' })
    const c = acct({ id: 'c', name: 'BofA Checking' })
    const groups = findAccountDuplicates([a, b, c])
    expect(groups).toHaveLength(1)
    expect(groups[0].accounts.map((x) => x.id).sort()).toEqual(['a', 'b'])
  })

  it('does not group across different types', () => {
    const a = acct({ id: 'a', name: 'Vanguard', type: 'brokerage' })
    const b = acct({ id: 'b', name: 'Vanguard', type: 'retirement' })
    expect(findAccountDuplicates([a, b])).toEqual([])
  })

  it('does not group when one has last4 and the other does not', () => {
    const a = acct({ id: 'a', name: 'Chase Checking', account_number_last4: '1234' })
    const b = acct({ id: 'b', name: 'Chase Checking' })
    // last4 is the stronger signal; the other lookups by name only.
    expect(findAccountDuplicates([a, b])).toEqual([])
  })

  it('skips rows with empty name and no last4', () => {
    const a = acct({ id: 'a', name: '' })
    const b = acct({ id: 'b', name: '' })
    expect(findAccountDuplicates([a, b])).toEqual([])
  })

  it('returns empty when nothing duplicates', () => {
    const a = acct({ id: 'a', name: 'Chase' })
    const b = acct({ id: 'b', name: 'Bofa' })
    expect(findAccountDuplicates([a, b])).toEqual([])
  })
})
