// Shared types mirroring the backend response shapes for `/engine/snapshot`,
// `/finance/goals`, and `/finance/accounts`. Keep in sync with the
// corresponding Pydantic models in backend/app/finance/schemas.py and the
// snapshot dict produced by backend/app/engine/snapshot.py.

export interface Snapshot {
  net_worth: number
  liquid_net_worth: number
  liquid_assets: number
  investment_assets: number
  non_current_assets: number
  total_liabilities: number
}

export interface Goal {
  id: string
  name: string
  type: string
  target_amount: number
  target_date: string
  current_progress: number
  feasibility_score: number | null
  status: string
  is_primary?: boolean | null
}

export interface Account {
  id: string
  name: string
  nickname?: string | null
  account_number_last4?: string | null
  type: string
  balance: number
  // Server-computed display value (mirrors backend snapshot.notional_value).
  // For checking/savings/brokerage/retirement/debt this matches `balance`.
  // For property/RSU/business it's a computed estimate.
  notional_value?: number | null
  estimated_value?: number | null
  purchase_price?: number | null
  vested_shares?: number | null
  unvested_shares?: number | null
  grant_price?: number | null
  vesting_schedule?: object[] | null
  ownership_pct?: number | null
  estimated_valuation?: number | null
  liquidity_horizon_months?: number | null
  // Balance-history trail. Surfaced under each row in the Accounts tab so the
  // user can see when an upload has overwritten what they entered manually.
  balance_updated_at?: string | null
  previous_balance?: number | null
  previous_balance_at?: string | null
}

export type CategoryBaselineTier = 'T1' | 'T2' | 'T3' | 'T4'

export interface CategoryBaseline {
  category: string
  tier: CategoryBaselineTier
  median_monthly: number
  mad: number
  months_observed: number
  next_month_expected: number
  seasonal_multiplier: number | null
}

export interface ExpenseBudgetWarning {
  stated_monthly_expenses: number
  baselined_total: number
  delta_pct: number
}

export interface CashFlowMonth {
  month: string
  balance: number
  monthly_net: number
  fixed_inflow: number
  fixed_outflow: number
  vesting_income: number
  projected_expense_expected?: number
  projected_expense_low?: number
  projected_expense_high?: number
}

export interface CashFlowResponse {
  income_expense_history_available?: boolean
  cashflow: CashFlowMonth[]
  category_baselines: CategoryBaseline[]
  expense_budget_warning: ExpenseBudgetWarning | null
  residual_monthly_expenses: number
  monthly_income: number
}

export type NetWorthNodeKind = 'root' | 'class' | 'type' | 'account'

export interface NetWorthNode {
  id: string
  name: string
  kind: NetWorthNodeKind
  value: number
  signed_value: number
  account_type?: string
  children?: NetWorthNode[]
}

export interface CashFlowPoint {
  month: string   // YYYY-MM
  balance: number
  net?: number
}
