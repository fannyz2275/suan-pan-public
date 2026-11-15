import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import api from '@/lib/api'
import { formatCurrency as fmt } from '@/lib/formatters'
import type { Goal } from '@/lib/types'

interface Props {
  goals: Goal[]
  onChanged?: () => void
}

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  on_track: 'default',
  at_risk: 'outline',
  off_track: 'destructive',
}

export default function GoalCard({ goals, onChanged }: Props) {
  // Track which goal is mid-toggle so we can disable the button briefly and
  // surface a transient error inline if the PATCH fails.
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (goals.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>Goals</CardTitle></CardHeader>
        <CardContent className="text-muted-foreground text-sm">No active goals. Chat with your advisor to set one up.</CardContent>
      </Card>
    )
  }

  // Sort primary goals first so the user's pinned goals are always at top.
  // Secondary sort keeps existing array order stable.
  const sorted = [...goals].sort((a, b) => Number(b.is_primary ?? false) - Number(a.is_primary ?? false))

  const togglePrimary = async (g: Goal) => {
    setPending(g.id)
    setError(null)
    try {
      await api.patch(`/finance/goals/${g.id}`, { is_primary: !g.is_primary })
      onChanged?.()
    } catch {
      setError('Failed to update. Please try again.')
    } finally {
      setPending(null)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle>Goals</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {sorted.map((g) => {
          const pct = g.target_amount > 0 ? Math.min(100, (g.current_progress / g.target_amount) * 100) : 0
          const isPrimary = !!g.is_primary
          return (
            <div key={g.id} className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <button
                    type="button"
                    onClick={() => togglePrimary(g)}
                    disabled={pending === g.id}
                    aria-label={isPrimary ? 'Unmark as primary goal' : 'Mark as primary goal'}
                    aria-pressed={isPrimary}
                    title={isPrimary ? 'Primary goal — click to unpin' : 'Mark as primary'}
                    className={`shrink-0 text-base leading-none transition-opacity ${
                      isPrimary ? 'text-yellow-500' : 'text-muted-foreground hover:text-yellow-500 opacity-60 hover:opacity-100'
                    } ${pending === g.id ? 'opacity-40 cursor-wait' : ''}`}
                  >
                    {isPrimary ? '★' : '☆'}
                  </button>
                  <span className="font-medium text-sm truncate">{g.name}</span>
                </div>
                <Badge variant={STATUS_VARIANT[g.status] ?? 'secondary'}>
                  {g.status?.replace('_', ' ')}
                </Badge>
              </div>
              <Progress value={pct} className="h-2" />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{fmt(g.current_progress)} of {fmt(g.target_amount)}</span>
                <span>by {g.target_date}</span>
              </div>
              {g.feasibility_score !== null && (
                <p className="text-xs text-muted-foreground">Feasibility: {g.feasibility_score}%</p>
              )}
            </div>
          )
        })}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </CardContent>
    </Card>
  )
}
