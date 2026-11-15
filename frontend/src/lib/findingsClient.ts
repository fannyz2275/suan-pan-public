import api from '@/lib/api'

export type FindingKind = 'recurring' | 'transfer'

export interface Finding {
  id: string
  kind: FindingKind
  title: string
  body: string
  evidence: Record<string, unknown>
  created_at: string
}

export interface FindingsResponse {
  findings: Finding[]
  total: number
}

export async function fetchFindings(): Promise<FindingsResponse> {
  const { data } = await api.get<FindingsResponse>('/findings')
  return data
}

export async function fetchFindingsCount(): Promise<number> {
  const { data } = await api.get<{ count: number }>('/findings/count')
  return data.count
}

export async function postFindingDecision(
  kind: FindingKind,
  id: string,
  decision: 'accept' | 'reject',
): Promise<{ status: string; previous?: string }> {
  const { data } = await api.post(`/findings/${kind}/${id}/decision`, { decision })
  return data
}

export async function startFindingsReview(): Promise<{ session_id: string; count: number } | null> {
  const res = await api.post('/advisor/findings/start')
  if (res.status === 204) return null
  return res.data
}
