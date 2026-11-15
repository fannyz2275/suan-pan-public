import { describe, it, expect } from 'vitest'
import {
  computeBreakdown,
  computeAnchor,
  type Transaction,
  type RuleBinding,
} from '../categoryBreakdown'

/*
 * Expected rendering for the fixture below at range=3M, anchor=2026-04-18:
 *
 * │ Month   │  Salary  │ Interest │ Utilities│ Dining   │  Travel  │ Groceries│ Inflow  │ Outflow │   Net    │
 * │ Apr '26 │  +6,200  │    +42   │   -240   │   -315   │    -90   │   -812   │ +6,242  │ -1,457  │  +4,785  │
 * │ Mar '26 │  +6,200  │    +38   │   -221   │   -410   │ -1,280   │ -904 ↻⚠ │ +6,238  │ -2,815  │  +3,423  │
 * │ Feb '26 │  +6,200  │    +35   │   -235   │   -295   │     0    │   -760   │ +6,235  │ -1,290  │  +4,945  │
 * │ Total   │ +18,600  │   +115   │   -696   │ -1,020   │ -1,370   │  -2,476  │+18,715  │ -5,562  │ +13,153  │
 */

const WF_RULE_ID = 'wf-rule-uuid'
const ANCHOR = new Date(2026, 3, 18)  // 2026-04-18

const fixture: Transaction[] = [
  // April
  { id: 't-apr-salary',   date: '2026-04-01', amount: 6200,    category: 'Salary',    description: 'Employer Direct Deposit' },
  { id: 't-apr-interest', date: '2026-04-03', amount: 42,      category: 'Interest',  description: 'Chase Savings Interest' },
  { id: 't-apr-utilities',date: '2026-04-05', amount: -240,    category: 'Utilities', description: 'PG&E' },
  { id: 't-apr-dining',   date: '2026-04-10', amount: -315,    category: 'Dining',    description: 'Sweetgreen' },
  { id: 't-apr-travel',   date: '2026-04-12', amount: -90,     category: 'Travel',    description: 'BART' },
  { id: 't-apr-wf-1',     date: '2026-04-04', amount: -280,    category: 'Groceries', description: 'Whole Foods Market' },
  { id: 't-apr-wf-2',     date: '2026-04-14', amount: -260,    category: 'Groceries', description: 'Whole Foods Market' },
  { id: 't-apr-safeway',  date: '2026-04-22', amount: -272,    category: 'Groceries', description: 'Safeway' },

  // March
  { id: 't-mar-salary',   date: '2026-03-01', amount: 6200,    category: 'Salary',    description: 'Employer Direct Deposit' },
  { id: 't-mar-interest', date: '2026-03-03', amount: 38,      category: 'Interest',  description: 'Chase Savings Interest' },
  { id: 't-mar-utilities',date: '2026-03-06', amount: -221,    category: 'Utilities', description: 'PG&E' },
  { id: 't-mar-dining',   date: '2026-03-18', amount: -410,    category: 'Dining',    description: 'Sweetgreen' },
  { id: 't-mar-travel',   date: '2026-03-24', amount: -1280,   category: 'Travel',    description: 'United Airlines' },
  { id: 't-mar-wf',       date: '2026-03-07', amount: -290,    category: 'Groceries', description: 'Whole Foods Market' },
  { id: 't-mar-costco',   date: '2026-03-14', amount: -289.66, category: 'Groceries', description: 'Costco Wholesale', transfer_status: 'needs_review' },
  { id: 't-mar-safeway',  date: '2026-03-28', amount: -324.34, category: 'Groceries', description: 'Safeway' },

  // February
  { id: 't-feb-salary',   date: '2026-02-01', amount: 6200,    category: 'Salary',    description: 'Employer Direct Deposit' },
  { id: 't-feb-interest', date: '2026-02-03', amount: 35,      category: 'Interest',  description: 'Chase Savings Interest' },
  { id: 't-feb-utilities',date: '2026-02-05', amount: -235,    category: 'Utilities', description: 'PG&E' },
  { id: 't-feb-dining',   date: '2026-02-12', amount: -295,    category: 'Dining',    description: 'Chipotle' },
  { id: 't-feb-safeway',  date: '2026-02-08', amount: -400,    category: 'Groceries', description: 'Safeway' },
  { id: 't-feb-tj',       date: '2026-02-20', amount: -360,    category: 'Groceries', description: "Trader Joe's" },
]

const bindings: RuleBinding[] = [
  { transaction_id: 't-apr-wf-1', rule_id: WF_RULE_ID, rule_keyword: 'Whole Foods', rule_frequency: 'weekly' },
  { transaction_id: 't-apr-wf-2', rule_id: WF_RULE_ID, rule_keyword: 'Whole Foods', rule_frequency: 'weekly' },
  { transaction_id: 't-mar-wf',   rule_id: WF_RULE_ID, rule_keyword: 'Whole Foods', rule_frequency: 'weekly' },
]

describe('computeBreakdown — golden fixture', () => {
  const b = computeBreakdown(fixture, bindings, '3M', ANCHOR)

  it('orders months newest first', () => {
    expect(b.months).toEqual(['2026-04', '2026-03', '2026-02'])
  })

  it('sorts categories by signed colTotal desc, ties alphabetical', () => {
    expect(b.categories).toEqual(['Salary', 'Interest', 'Utilities', 'Dining', 'Travel', 'Groceries'])
  })

  it('reproduces every cell in the mockup', () => {
    expect(b.cells['2026-04']['Salary'].total).toBe(6200)
    expect(b.cells['2026-04']['Interest'].total).toBe(42)
    expect(b.cells['2026-04']['Utilities'].total).toBe(-240)
    expect(b.cells['2026-04']['Dining'].total).toBe(-315)
    expect(b.cells['2026-04']['Travel'].total).toBe(-90)
    expect(b.cells['2026-04']['Groceries'].total).toBe(-812)

    expect(b.cells['2026-03']['Salary'].total).toBe(6200)
    expect(b.cells['2026-03']['Interest'].total).toBe(38)
    expect(b.cells['2026-03']['Utilities'].total).toBe(-221)
    expect(b.cells['2026-03']['Dining'].total).toBe(-410)
    expect(b.cells['2026-03']['Travel'].total).toBe(-1280)
    expect(b.cells['2026-03']['Groceries'].total).toBe(-904)

    expect(b.cells['2026-02']['Salary'].total).toBe(6200)
    expect(b.cells['2026-02']['Interest'].total).toBe(35)
    expect(b.cells['2026-02']['Utilities'].total).toBe(-235)
    expect(b.cells['2026-02']['Dining'].total).toBe(-295)
    expect(b.cells['2026-02']['Groceries'].total).toBe(-760)
    expect(b.cells['2026-02']['Travel']).toBeUndefined()
  })

  it('computes row totals Inflow/Outflow/Net per month', () => {
    expect(b.rowTotals['2026-04']).toEqual({ inflow: 6242, outflow: -1457, net: 4785 })
    expect(b.rowTotals['2026-03']).toEqual({ inflow: 6238, outflow: -2815, net: 3423 })
    expect(b.rowTotals['2026-02']).toEqual({ inflow: 6235, outflow: -1290, net: 4945 })
  })

  it('computes column totals', () => {
    expect(b.colTotals['Salary']).toBe(18600)
    expect(b.colTotals['Interest']).toBe(115)
    expect(b.colTotals['Utilities']).toBe(-696)
    expect(b.colTotals['Dining']).toBe(-1020)
    expect(b.colTotals['Travel']).toBe(-1370)
    expect(b.colTotals['Groceries']).toBe(-2476)
  })

  it('computes grand total', () => {
    expect(b.grand).toEqual({ inflow: 18715, outflow: -5562, net: 13153 })
  })

  it('propagates hasNeedsReview onto the correct cell only', () => {
    expect(b.cells['2026-03']['Groceries'].hasNeedsReview).toBe(true)
    expect(b.cells['2026-04']['Groceries'].hasNeedsReview).toBe(false)
    expect(b.cells['2026-02']['Groceries'].hasNeedsReview).toBe(false)
    expect(b.cells['2026-03']['Utilities'].hasNeedsReview).toBe(false)
  })

  it('propagates hasRecurring onto cells with matched transactions', () => {
    expect(b.cells['2026-04']['Groceries'].hasRecurring).toBe(true)
    expect(b.cells['2026-03']['Groceries'].hasRecurring).toBe(true)
    expect(b.cells['2026-02']['Groceries'].hasRecurring).toBe(false)
    expect(b.cells['2026-04']['Salary'].hasRecurring).toBe(false)
  })

  it('counts recurring occurrences in the visible window', () => {
    expect(b.ruleCountsInWindow[WF_RULE_ID]).toBe(3)
  })
})

describe('computeBreakdown — edge cases', () => {
  it('returns empty structure for empty transactions', () => {
    const b = computeBreakdown([], [], '3M', ANCHOR)
    expect(b.categories).toEqual([])
    expect(b.grand).toEqual({ inflow: 0, outflow: 0, net: 0 })
    expect(Object.keys(b.ruleCountsInWindow)).toEqual([])
  })

  it('1M range drops months outside the window', () => {
    const b = computeBreakdown(fixture, bindings, '1M', ANCHOR)
    expect(b.months).toEqual(['2026-04'])
    expect(b.cells['2026-03']).toBeUndefined()
    expect(b.colTotals['Salary']).toBe(6200)
  })

  it('null category buckets into "Other"', () => {
    const withNull: Transaction[] = [
      { id: 'x1', date: '2026-04-05', amount: -50, category: null, description: 'mystery' },
    ]
    const b = computeBreakdown(withNull, [], '3M', ANCHOR)
    expect(b.categories).toEqual(['Other'])
    expect(b.cells['2026-04']['Other'].total).toBe(-50)
  })

  it('no bindings → hasRecurring false everywhere, empty ruleCountsInWindow', () => {
    const b = computeBreakdown(fixture, [], '3M', ANCHOR)
    for (const m of b.months) {
      for (const c of b.categories) {
        expect(b.cells[m][c]?.hasRecurring ?? false).toBe(false)
      }
    }
    expect(b.ruleCountsInWindow).toEqual({})
  })
})

describe('computeAnchor', () => {
  it('returns the max transaction date', () => {
    const anchor = computeAnchor(fixture)
    expect(anchor.getFullYear()).toBe(2026)
    expect(anchor.getMonth()).toBe(3)  // April
    expect(anchor.getDate()).toBe(22)
  })

  it('falls back to the provided date when empty', () => {
    const fallback = new Date(2025, 0, 1)
    expect(computeAnchor([], fallback)).toBe(fallback)
  })
})
