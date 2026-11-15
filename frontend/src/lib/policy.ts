import api from './api'

export type Domain = 'categorize' | 'transfers' | 'recurring' | 'feasibility' | 'baseline'

export interface LearnedOverride {
  id: string
  domain: Domain
  key: string
  value: Record<string, unknown>
  strength: number
  last_reinforced_at: string
  created_at: string
}

export interface ToolPrior {
  tool_name: string
  ctx_signature: string
  success_count: number
  miss_count: number
  utility_score: number
  last_used_at: string | null
}

export interface LearnedResponse {
  overrides: LearnedOverride[]
  tool_priors: ToolPrior[]
}

export async function fetchLearnedPolicies(): Promise<LearnedResponse> {
  const res = await api.get<LearnedResponse>('/policy/me')
  return res.data
}

export async function forgetOverride(id: string): Promise<void> {
  await api.delete(`/policy/overrides/${id}`)
}

/** Render a learned override as a one-line, plain-English description.
 * The shape of `value` is domain-specific; this central renderer keeps
 * the LearnedPoliciesCard component dumb.
 */
export function describeOverride(o: LearnedOverride): string {
  const stripped = o.key.replace(/^[a-z_]+:/, '')
  switch (o.domain) {
    case 'categorize': {
      const cat = (o.value?.category as string) ?? '?'
      return `Categorize "${stripped}" as ${cat}`
    }
    case 'transfers':
      return `Treat "${stripped}" as external (skip transfer pairing)`
    case 'recurring':
      return `Don't propose "${stripped}" as a recurring rule`
    case 'feasibility':
    case 'baseline':
      return `${o.domain}: ${stripped}`
    default:
      return `${o.domain}: ${stripped}`
  }
}
