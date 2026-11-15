import api from '@/lib/api'

export interface ReviewRow {
  txn_id: string
  date: string
  description: string
  amount: number
  account_name: string
  transfer_status: 'auto_paired' | 'needs_review'
  group_id: string | null
  suggested_match: {
    txn_id: string
    date: string
    amount: number
    account_name: string
  } | null
}

export type ReviewWindow = '90d' | 'all'

export async function fetchReview(
  window: ReviewWindow = '90d',
): Promise<ReviewRow[]> {
  const { data } = await api.get<ReviewRow[]>('/engine/transfers/review', {
    params: { window },
    timeout: 20000,
  })
  return data
}

export async function rescan(): Promise<{ paired: number; orphans: number }> {
  const { data } = await api.post<{ paired: number; orphans: number }>(
    '/engine/transfers/rescan',
  )
  return data
}

export async function linkTransactions(txnId: string, otherTxnId: string): Promise<void> {
  await api.post(`/engine/transfers/${txnId}/link`, { other_txn_id: otherTxnId })
}

export async function markExternal(txnId: string): Promise<void> {
  await api.post(`/engine/transfers/${txnId}/mark-external`)
}

export async function dismiss(txnId: string): Promise<void> {
  await api.post(`/engine/transfers/${txnId}/dismiss`)
}

export async function confirmPair(txnId: string): Promise<void> {
  try {
    await api.post(`/engine/transfers/${txnId}/confirm`, undefined, { timeout: 20000 })
  } catch (error) {
    if ((error as { code?: string }).code === 'ECONNABORTED') {
      throw new Error('Confirmation timed out; it may have saved. Reload transfers before retrying.')
    }
    throw error
  }
}
