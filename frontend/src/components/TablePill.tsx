import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

export interface TableColumn {
  key: string
  label: string
  align?: 'left' | 'right'
  format?: 'currency'
}

export interface DisplayableTable {
  title: string
  summary: string
  columns: TableColumn[]
  rows: Record<string, unknown>[]
}

interface Props {
  table: DisplayableTable
  defaultOpen?: boolean
}

const FULL_VIEW_THRESHOLD = 100

function formatCell(value: unknown, format: TableColumn['format']): ReactNode {
  if (value === null || value === undefined || value === '') return '—'
  if (format === 'currency' && typeof value === 'number') {
    const sign = value < 0 ? '−' : ''
    const abs = Math.abs(value).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
    return (
      <span className={value < 0 ? 'text-rose-700' : value > 0 ? 'text-emerald-700' : ''}>
        {sign}${abs}
      </span>
    )
  }
  return String(value)
}

export default function TablePill({ table, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen)
  const rowCount = table.rows.length
  const tooLarge = rowCount > FULL_VIEW_THRESHOLD

  return (
    <div data-testid="table-pill" className="mt-1.5 mb-2 border border-border rounded-lg overflow-hidden bg-background max-w-[88%]">
      <button
        data-testid="table-pill-toggle"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-3 py-2 bg-muted hover:bg-muted/70 text-xs text-left transition-colors"
      >
        <span className="flex items-center gap-2 min-w-0">
          <span className="font-semibold text-foreground truncate">{table.title}</span>
          <span className="text-muted-foreground whitespace-nowrap">· {table.summary}</span>
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform ${
            open ? 'rotate-180' : ''
          }`}
        />
      </button>
      {open && (
        <div data-testid="table-pill-body">
          <div className="max-h-[280px] overflow-auto border-t border-border">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr>
                  {table.columns.map((col) => (
                    <th
                      key={col.key}
                      className={`sticky top-0 z-10 bg-muted/50 px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground border-b border-border ${
                        col.align === 'right' ? 'text-right' : 'text-left'
                      }`}
                    >
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, i) => (
                  <tr key={i} className="hover:bg-muted/30">
                    {table.columns.map((col) => (
                      <td
                        key={col.key}
                        className={`px-3 py-1.5 border-b border-border/50 align-top ${
                          col.align === 'right' ? 'text-right tabular-nums' : ''
                        }`}
                      >
                        {formatCell(row[col.key], col.format)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex justify-between items-center px-3 py-1.5 border-t border-border bg-muted/30 text-[11px] text-muted-foreground">
            <span>
              {rowCount} row{rowCount === 1 ? '' : 's'} · scroll for more
            </span>
            {tooLarge && (
              <button
                type="button"
                className="text-primary hover:underline font-medium"
                onClick={() => {
                  // TODO: hook up right-side drawer when row count > 100.
                }}
              >
                Open full view →
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
