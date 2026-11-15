import { Button } from '@/components/ui/button'
import type { Goal } from '@/lib/types'

interface Props {
  goals: Goal[]
  activeIds: string[]
  onChange: (next: string[]) => void
}

const MAX_ACTIVE = 3

export default function WhatIfGoalToggle({ goals, activeIds, onChange }: Props) {
  if (goals.length === 0) return null
  const toggle = (id: string) => {
    if (activeIds.includes(id)) {
      onChange(activeIds.filter((x) => x !== id))
    } else {
      if (activeIds.length >= MAX_ACTIVE) return
      onChange([...activeIds, id])
    }
  }
  return (
    <div className="flex flex-wrap gap-1.5 mt-2 items-center">
      <span className="text-xs text-muted-foreground">What if?</span>
      {goals.map((g) => {
        const active = activeIds.includes(g.id)
        const disabled = !active && activeIds.length >= MAX_ACTIVE
        return (
          <button
            key={g.id}
            type="button"
            disabled={disabled}
            onClick={() => toggle(g.id)}
            aria-pressed={active}
            className={`text-[11px] leading-none px-2 py-1 rounded-full ring-1 transition-colors disabled:opacity-50 ${
              active
                ? 'bg-amber-100 text-amber-900 ring-amber-500'
                : 'text-amber-700 ring-amber-300 hover:bg-amber-50'
            }`}
          >
            {g.name}
          </button>
        )
      })}
      {activeIds.length > 0 && (
        <Button
          size="sm"
          variant="ghost"
          className="text-[11px] h-6 px-2"
          onClick={() => onChange([])}
        >
          Clear all
        </Button>
      )}
    </div>
  )
}
