import api from '@/lib/api'

export type Frequency =
  | 'weekly' | 'biweekly' | 'semi_monthly'
  | 'monthly' | 'quarterly' | 'semi_annual' | 'annual'

export type Direction = 'income' | 'expense'

export type RecurringStatus =
  | 'proposed' | 'pending_review' | 'auto_applied'
  | 'user_confirmed' | 'user_rejected'

export type RecurringSource = 'heuristic' | 'llm' | 'user_created'

export interface RecurringRule {
  id: string
  user_id: string
  keyword: string
  normalized_key_pattern: string
  amount_min: number
  amount_max: number
  amount_median: number
  frequency: Frequency
  direction: Direction
  confidence: number
  status: RecurringStatus
  source: RecurringSource
  last_seen_date: string | null
  next_expected_date: string | null
  occurrences_observed: number
  sample_transaction_ids: string[]
  created_at?: string
  updated_at?: string
}

export async function runDetection(): Promise<RecurringRule[]> {
  const { data } = await api.post<{ rules: RecurringRule[] }>('/engine/recurring/detect', undefined, { timeout: 45_000 })
  return data.rules
}

export async function listRules(): Promise<RecurringRule[]> {
  const { data } = await api.get<{ rules: RecurringRule[] }>('/engine/recurring/rules')
  return data.rules
}

export type PatchAction =
  | { action: 'confirm' }
  | { action: 'reject' }
  | {
      action: 'edit'
      keyword?: string
      amount_min?: number
      amount_max?: number
      frequency?: Frequency
    }

export async function patchRule(id: string, body: PatchAction): Promise<RecurringRule> {
  const { data } = await api.patch<RecurringRule>(`/engine/recurring/rules/${id}`, body)
  return data
}
