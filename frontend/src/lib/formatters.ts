// Whole-dollar USD format (default for cards, totals, account balances).
const wholeDollar = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

// Cents precision for transaction-level amounts.
const cents = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

// Compact ($1.2K, $5M) for chart axes.
const compact = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  style: 'currency',
  currency: 'USD',
})

export function formatCurrency(n: number): string {
  return wholeDollar.format(n)
}

export function formatCurrencyCents(n: number): string {
  return cents.format(n)
}

export function formatCompactCurrency(n: number): string {
  return compact.format(n)
}

// Returns "—" for zero so tables don't get noisy. `signed` adds a leading +/-.
export function formatCurrencySigned(
  n: number,
  opts: { signed?: boolean } = {},
): string {
  if (n === 0) return '—'
  const body = wholeDollar.format(Math.abs(n))
  if (opts.signed) return n > 0 ? `+${body}` : `-${body}`
  return n < 0 ? `-${body}` : body
}

// Always-signed cents format (used in transaction lists where the sign carries
// meaning, e.g. "+$42.18" / "-$13.49").
export function formatCurrencyCentsSigned(n: number): string {
  const sign = n >= 0 ? '+' : '-'
  return `${sign}$${new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(n))}`
}

// Short date label for inline metadata, e.g. "Apr 28, 2026". Falls back to
// the raw input string if it doesn't parse, so we never silently render a
// misleading date.
const shortDate = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

export function formatShortDate(value: string | Date | null | undefined): string | null {
  if (!value) return null
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return null
  return shortDate.format(d)
}
