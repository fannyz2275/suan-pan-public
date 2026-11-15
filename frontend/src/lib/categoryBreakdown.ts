export type Range = '1M' | '3M' | '6M' | '1Y'

export const RANGE_MONTHS: Record<Range, number> = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12 }

export interface Transaction {
  id: string
  date: string
  amount: number
  category: string | null
  description?: string
  transfer_status?: string | null
}

export interface RuleBinding {
  transaction_id: string
  rule_id: string
  rule_keyword: string
  rule_frequency: string
}

export interface CellData {
  total: number
  transactions: Transaction[]
  hasNeedsReview: boolean
  hasRecurring: boolean
}

export interface RowTotals {
  inflow: number
  outflow: number
  net: number
}

export interface Breakdown {
  months: string[]
  categories: string[]
  cells: Record<string, Record<string, CellData>>
  rowTotals: Record<string, RowTotals>
  colTotals: Record<string, number>
  grand: RowTotals
  ruleCountsInWindow: Record<string, number>
  bindingByTxnId: Record<string, RuleBinding>
}

function parseIsoDate(s: string): Date {
  // Parse "YYYY-MM-DD" as a local-time date so month math doesn't drift on TZ boundaries.
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function monthKey(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  return `${y}-${m}`
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

export function computeAnchor(transactions: Transaction[], fallback: Date = new Date()): Date {
  if (transactions.length === 0) return fallback
  let latest = parseIsoDate(transactions[0].date)
  for (const t of transactions) {
    const d = parseIsoDate(t.date)
    if (d > latest) latest = d
  }
  return latest
}

export function computeBreakdown(
  transactions: Transaction[],
  bindings: RuleBinding[],
  range: Range,
  anchor: Date,
): Breakdown {
  const bindingByTxnId: Record<string, RuleBinding> = {}
  for (const b of bindings) bindingByTxnId[b.transaction_id] = b

  const monthsInWindow: string[] = []
  const windowMonths = RANGE_MONTHS[range]
  for (let i = 0; i < windowMonths; i++) {
    const d = new Date(anchor.getFullYear(), anchor.getMonth() - i, 1)
    monthsInWindow.push(monthKey(d))
  }
  const monthSet = new Set(monthsInWindow)

  const cells: Record<string, Record<string, CellData>> = {}
  const colTotals: Record<string, number> = {}
  const ruleCountsInWindow: Record<string, number> = {}

  for (const month of monthsInWindow) cells[month] = {}

  for (const t of transactions) {
    const mk = t.date.slice(0, 7)
    if (!monthSet.has(mk)) continue
    const cat = t.category ?? 'Other'
    if (!cells[mk][cat]) {
      cells[mk][cat] = { total: 0, transactions: [], hasNeedsReview: false, hasRecurring: false }
    }
    const cell = cells[mk][cat]
    cell.total = round2(cell.total + t.amount)
    cell.transactions.push(t)
    if (t.transfer_status === 'needs_review') cell.hasNeedsReview = true
    const binding = bindingByTxnId[t.id]
    if (binding) {
      cell.hasRecurring = true
      ruleCountsInWindow[binding.rule_id] = (ruleCountsInWindow[binding.rule_id] ?? 0) + 1
    }
    colTotals[cat] = round2((colTotals[cat] ?? 0) + t.amount)
  }

  const categories = Object.keys(colTotals).sort((a, b) => {
    const diff = colTotals[b] - colTotals[a]
    if (diff !== 0) return diff
    return a.localeCompare(b)
  })

  const rowTotals: Record<string, RowTotals> = {}
  const grand: RowTotals = { inflow: 0, outflow: 0, net: 0 }
  for (const month of monthsInWindow) {
    let inflow = 0
    let outflow = 0
    for (const cat of categories) {
      const cell = cells[month][cat]
      if (!cell) continue
      if (cell.total > 0) inflow += cell.total
      else outflow += cell.total
    }
    rowTotals[month] = {
      inflow: round2(inflow),
      outflow: round2(outflow),
      net: round2(inflow + outflow),
    }
    grand.inflow = round2(grand.inflow + inflow)
    grand.outflow = round2(grand.outflow + outflow)
  }
  grand.net = round2(grand.inflow + grand.outflow)

  return {
    months: monthsInWindow,
    categories,
    cells,
    rowTotals,
    colTotals,
    grand,
    ruleCountsInWindow,
    bindingByTxnId,
  }
}
