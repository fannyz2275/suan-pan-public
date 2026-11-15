export interface BulkPreview {
  mode: 'preview' | 'executed' | 'error'
  matched: Array<{ id: string; date: string; description: string; amount: number; old_category: string | null }>
  new_category: string
  updated_count: number
  failed_ids: string[]
}

interface Props {
  preview: BulkPreview
  onConfirm: () => void
  onCancel: () => void
  /** When true, both buttons are disabled — used to block double-submits
   * while the parent is streaming the confirmed request. */
  disabled?: boolean
}

export default function BulkRecategorizeConfirmCard({ preview, onConfirm, onCancel, disabled = false }: Props) {
  // Defensive: a preview with no category, no matches, or an explicit error
  // mode should not surface a Confirm button — it would be a no-op (or
  // worse, apply a blank category). Render an error chip with a single
  // dismiss action instead.
  const hasCategory = !!preview.new_category && preview.new_category.trim().length > 0
  const isError = preview.mode === 'error' || !hasCategory || preview.matched.length === 0
  if (isError) {
    return (
      <div className="border rounded-lg p-4 my-2 bg-destructive/5 border-destructive/30">
        <p className="text-sm font-medium mb-1">Recategorize tool failed</p>
        <p className="text-xs text-muted-foreground mb-3">
          {!hasCategory
            ? 'No category specified. Ask the advisor to retry with a valid category (Food, Transport, Shopping, Housing, Entertainment, Health, Bills, Transfer, Income, Other).'
            : preview.matched.length === 0
              ? 'No transactions matched the description pattern.'
              : 'The tool returned an error.'}
        </p>
        <div className="flex gap-2 justify-end">
          <button type="button" onClick={onCancel} className="px-3 py-1 border rounded text-sm">Dismiss</button>
        </div>
      </div>
    )
  }
  const shown = preview.matched.slice(0, 3)
  const overflow = preview.matched.length - shown.length
  return (
    <div className="border rounded-lg p-4 my-2 bg-muted/40">
      <p className="text-sm font-medium mb-2">
        Apply category '{preview.new_category}' to {preview.matched.length} txns:
      </p>
      <ul className="text-xs space-y-1 mb-3 font-mono">
        {shown.map((m) => (
          <li key={m.id}>
            {m.date}  {m.description}  ${Math.abs(m.amount).toFixed(2)}
          </li>
        ))}
        {overflow > 0 && <li className="text-muted-foreground">… +{overflow} more</li>}
      </ul>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onCancel} disabled={disabled} className="px-3 py-1 border rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed">Cancel</button>
        <button type="button" onClick={onConfirm} disabled={disabled} className="px-3 py-1 bg-primary text-primary-foreground rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed">Confirm</button>
      </div>
    </div>
  )
}
