import type { ScaleAnchor } from '@/lib/profileScales'

interface Props {
  /** Current scalar value (1-5). null means unset. */
  value: number | null | undefined
  /** Anchor sentences keyed by value. Loaded once via lib/profileScales. */
  anchors: ScaleAnchor[] | null
  /** Form-field label. */
  label: string
  /** Required for screen readers + RTL queries. */
  ariaLabel: string
  /**
   * False = the slider currently shows a default placeholder, not a real
   * user choice. The component renders a muted hint so users know they
   * haven't set a value yet. Parent flips this to true on first onChange.
   */
  dirty?: boolean
  onChange: (next: number) => void
}

/**
 * 1-5 slider whose tooltip shows the anchor sentence at the current notch.
 * The anchors come from GET /profile/scales — the backend rendering of
 * "Risk N/5 (label)" and the UI tooltip share a single source of truth.
 *
 * Renders three lines:
 *   • the inline label + "N/5 (short label)"
 *   • the slider itself
 *   • the full sentence below, anchored to the current value
 */
export default function Slider15({ value, anchors, label, ariaLabel, onChange, dirty = true }: Props) {
  // Default to 3 (middle) when unset so the slider is always interactive.
  const v = value ?? 3

  const current = anchors?.find((a) => a.value === v) ?? null

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span>{label}</span>
        <span className="text-muted-foreground">
          {dirty ? `${v}/5${current ? ` (${current.label})` : ''}` : 'not set'}
        </span>
      </div>
      <input
        type="range"
        min={1}
        max={5}
        step={1}
        value={v}
        aria-label={ariaLabel}
        className="w-full"
        onChange={(e) => {
          const next = Number(e.target.value)
          onChange(next)
        }}
      />
      {current && (
        <div className="text-xs text-muted-foreground">
          {current.description}
        </div>
      )}
    </div>
  )
}
