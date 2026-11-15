import axios from 'axios'
import type { Account, CashFlowPoint, NetWorthNode } from './types'
import type { FeedbackLabels } from '../components/FeedbackBar'
import { supabase } from './supabase'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

const api = axios.create({ baseURL: BASE_URL })

api.interceptors.request.use(async (config) => {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export default api

export async function fetchNetWorthTree(): Promise<NetWorthNode> {
  const res = await api.get<NetWorthNode>('/engine/networth-tree')
  return res.data
}

export const accountsApi = {
  async create(payload: Partial<Account>): Promise<Account> {
    const res = await api.post<Account>('/finance/accounts', payload)
    return res.data
  },
  async update(id: string, patch: Partial<Account>): Promise<Account> {
    const res = await api.patch<Account>(`/finance/accounts/${id}`, patch)
    return res.data
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/finance/accounts/${id}`)
  },
}

export async function fetchCashFlowHistory(months = 12): Promise<CashFlowPoint[]> {
  const res = await api.get<CashFlowPoint[]>('/engine/cashflow-history', { params: { months } })
  return res.data
}

export interface CashFlowExplainPayload {
  projection: CashFlowPoint[]
  history: CashFlowPoint[]
  starting_balance: number
  monthly_income: number
  monthly_expenses: number
  vesting_events: Array<{ date: string; value: number }>
  fixed_recurring: { inflow: number; outflow: number }
}

export async function requestCashFlowExplanation(payload: CashFlowExplainPayload): Promise<string> {
  const res = await api.post<{ explanation: string }>('/engine/cashflow-explain', payload)
  return res.data.explanation
}

export interface ExpenseStatistic {
  value: number | null
  source: 'computed' | 'insufficient_data'
  sample_size: number
  window_days: number
}

export async function fetchExpenseStatistic(windowDays = 90): Promise<ExpenseStatistic> {
  const res = await api.get<ExpenseStatistic>('/engine/expenses-statistic', { params: { window_days: windowDays } })
  return res.data
}

export async function submitFeedback(messageId: string, labels: FeedbackLabels) {
  return api.post('/notes/feedback', { message_id: messageId, labels })
}
