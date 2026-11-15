import type { Account } from './types'

// Heuristic for detecting accounts that almost certainly represent the same
// real-world account but ended up as separate rows — typically because the
// import parser couldn't extract last4 from one or more statements and the
// Gemini-generated name varied slightly across uploads.
//
// Two accounts are grouped as duplicates when they share `type` AND either:
//   - the same `account_number_last4` (unambiguous), OR
//   - both lack `last4` AND have the same normalized name.
//
// Normalization lowercases, strips non-alphanumerics, and collapses
// whitespace, so "Chase Checking", "chase  checking", and "Chase-Checking"
// all collapse to the same key. We deliberately do NOT do fuzzy matching
// across names — false positives here would push the user toward merging
// genuinely separate accounts, which is destructive.

export function normalizeName(name: string | null | undefined): string {
  return (name ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

export interface DuplicateGroup {
  key: string
  type: string
  accounts: Account[]
}

export function findAccountDuplicates(accounts: Account[]): DuplicateGroup[] {
  const groups = new Map<string, DuplicateGroup>()
  for (const a of accounts) {
    const last4 = a.account_number_last4 || null
    const key = last4
      ? `${a.type}|last4:${last4}`
      : `${a.type}|name:${normalizeName(a.name)}`
    // Skip rows whose normalized name is empty AND have no last4 — there's
    // nothing to match on, so we'd create a giant catch-all group.
    if (!last4 && !normalizeName(a.name)) continue
    const existing = groups.get(key)
    if (existing) existing.accounts.push(a)
    else groups.set(key, { key, type: a.type, accounts: [a] })
  }
  return [...groups.values()].filter((g) => g.accounts.length >= 2)
}

export function buildDuplicateIdSet(groups: DuplicateGroup[]): Set<string> {
  const ids = new Set<string>()
  for (const g of groups) for (const a of g.accounts) ids.add(a.id)
  return ids
}
