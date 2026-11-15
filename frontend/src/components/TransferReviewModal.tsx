import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { formatCurrencyCents as fmtMoney } from '@/lib/formatters'
import {
  fetchReview,
  markExternal,
  dismiss,
  linkTransactions,
  confirmPair,
  type ReviewRow,
  type ReviewWindow,
} from '@/lib/transfers'

interface Props {
  open: boolean
  onClose: () => void
  onChanged: () => void
  onRequestUpload?: () => void
}

export default function TransferReviewModal({
  open,
  onClose,
  onChanged,
  onRequestUpload,
}: Props) {
  const [rows, setRows] = useState<ReviewRow[]>([])
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [windowMode, setWindowMode] = useState<ReviewWindow>('90d')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [progress, setProgress] = useState({ done: 0, total: 0 })

  const load = useCallback(
    async (mode: ReviewWindow, showSpinner = true) => {
      if (showSpinner) setLoading(true)
      try {
        setRows(await fetchReview(mode))
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not refresh transfers. Retry loading before confirming again.')
      } finally {
        if (showSpinner) setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    if (open) {
      setError(null)
      setSelected(new Set())
      void load(windowMode)
    }
  }, [open, windowMode, load])

  const act = useCallback(
    async (id: string, fn: () => Promise<unknown>) => {
      setBusyId(id)
      setError(null)
      try {
        await fn()
        setSelected((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
        await load(windowMode, false)
        onChanged()
      } catch (e) {
        const msg =
          (e as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? (e instanceof Error ? e.message : 'Action failed')
        setError(msg)
      } finally {
        setBusyId(null)
      }
    },
    [onChanged, load, windowMode],
  )

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const allSelected = rows.length > 0 && selected.size === rows.length
  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.txn_id)))
  }

  const selectedRows = useMemo(
    () => rows.filter((r) => selected.has(r.txn_id)),
    [rows, selected],
  )
  const selectedAutoIds = [...new Map(selectedRows
    .filter((r) => r.transfer_status === 'auto_paired')
    .map((r) => [r.group_id ?? r.txn_id, r.txn_id])).values()]
  const selectedAutoCount = selectedAutoIds.length

  const runBulk = useCallback(
    async (
      ids: string[],
      fn: (id: string) => Promise<unknown>,
      label: string,
    ) => {
      if (ids.length === 0) return
      setBulkBusy(true)
      setError(null)
      setProgress({ done: 0, total: ids.length })
      const failures: string[] = []
      let next = 0
      try {
        await Promise.all(
          Array.from({ length: Math.min(3, ids.length) }, async () => {
            while (next < ids.length) {
              const id = ids[next++]
              try {
                await fn(id)
              } catch (e) {
                const msg =
                  (e as { response?: { data?: { detail?: string } } })?.response
                    ?.data?.detail ??
                  (e instanceof Error ? e.message : 'Action failed')
                failures.push(`${id.slice(0, 6)}…: ${msg}`)
              } finally {
                setProgress((p) => ({ ...p, done: p.done + 1 }))
              }
            }
          }),
        )
        if (failures.length) {
          setError(
            `${label} — ${ids.length - failures.length} succeeded, ${failures.length} failed: ${failures.slice(0, 3).join('; ')}`,
          )
        }
        setSelected(new Set())
        await load(windowMode, false)
        onChanged()
      } finally {
        setBulkBusy(false)
      }
    },
    [onChanged, load, windowMode],
  )

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-background rounded-lg border shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h2 className="text-base font-semibold">Review transfers</h2>
          <Button size="sm" variant="ghost" onClick={onClose}>
            Close
          </Button>
        </div>

        {/* Toolbar */}
        <div className="px-5 py-2 border-b flex items-center justify-between gap-3 flex-wrap">
          <div className="inline-flex rounded-md border text-xs overflow-hidden">
            {(['90d', 'all'] as const).map((w) => (
              <button
                key={w}
                type="button"
                disabled={bulkBusy || busyId !== null}
                onClick={() => setWindowMode(w)}
                className={`px-3 py-1.5 ${
                  windowMode === w
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-background hover:bg-muted'
                }`}
              >
                {w === '90d' ? 'Last 90 days' : 'All time'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {rows.length > 0 && (
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  disabled={bulkBusy || busyId !== null}
                  checked={allSelected}
                  onChange={toggleAll}
                  className="h-3.5 w-3.5"
                />
                Select all ({rows.length})
              </label>
            )}
          </div>
        </div>

        {/* Bulk action bar */}
        {selected.size > 0 && (
          <div className="px-5 py-2 border-b bg-muted/40 flex items-center justify-between text-xs gap-2 flex-wrap">
            <span className="text-muted-foreground">
              {selected.size} selected
            </span>
            <div className="flex gap-2 flex-wrap">
              {selectedAutoCount > 0 && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={bulkBusy || busyId !== null}
                  onClick={() =>
                    runBulk(
                      selectedAutoIds,
                      confirmPair,
                      'Confirm',
                    )
                  }
                >
                  Confirm auto-paired ({selectedAutoCount})
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                disabled={bulkBusy || busyId !== null}
                onClick={() =>
                  runBulk(
                    selectedRows.map((r) => r.txn_id),
                    markExternal,
                    'Mark external',
                  )
                }
              >
                Mark external
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={bulkBusy || busyId !== null}
                onClick={() =>
                  runBulk(
                    selectedRows.map((r) => r.txn_id),
                    dismiss,
                    'Dismiss',
                  )
                }
              >
                Not a transfer
              </Button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto px-5 py-3">
          {bulkBusy && <p role="status" className="text-sm mb-3">Processing {progress.done} of {progress.total}...</p>}
          {error && (
            <div role="alert" className="mb-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-900">
              {error}
              <Button size="sm" variant="outline" disabled={bulkBusy || loading} onClick={() => { setError(null); void load(windowMode) }}>Retry loading</Button>
            </div>
          )}
          {loading ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              Loading…
            </div>
          ) : rows.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              Nothing to review in this window. Transfers are up to date.
            </div>
          ) : (
            <ul className="divide-y">
              {rows.map((r) => {
                const isAuto = r.transfer_status === 'auto_paired'
                const isSelected = selected.has(r.txn_id)
                return (
                  <li
                    key={r.txn_id}
                    className="py-3 flex items-center gap-3"
                  >
                    <input
                      type="checkbox"
                      disabled={bulkBusy || busyId !== null}
                      checked={isSelected}
                      onChange={() => toggleOne(r.txn_id)}
                      className="h-4 w-4 flex-shrink-0"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">
                        {r.description}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {r.date} · {r.account_name} · {fmtMoney(r.amount)} ·{' '}
                        <span className="uppercase tracking-wide">
                          {r.transfer_status.replace('_', ' ')}
                        </span>
                      </div>
                      {r.suggested_match && (
                        <div className="text-xs mt-1">
                          Suggested match: {r.suggested_match.date} ·{' '}
                          {r.suggested_match.account_name} ·{' '}
                          {fmtMoney(r.suggested_match.amount)}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-2 flex-shrink-0">
                      {isAuto ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busyId !== null || bulkBusy}
                          onClick={() =>
                            act(r.txn_id, () => confirmPair(r.txn_id))
                          }
                        >
                          Confirm
                        </Button>
                      ) : r.suggested_match ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busyId === r.txn_id || bulkBusy}
                          onClick={() =>
                            act(r.txn_id, () =>
                              linkTransactions(
                                r.txn_id,
                                r.suggested_match!.txn_id,
                              ),
                            )
                          }
                        >
                          Link
                        </Button>
                      ) : null}
                      {onRequestUpload && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={onRequestUpload}
                        >
                          Upload statement
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busyId === r.txn_id || bulkBusy}
                        onClick={() =>
                          act(r.txn_id, () => markExternal(r.txn_id))
                        }
                      >
                        External
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busyId === r.txn_id || bulkBusy}
                        onClick={() =>
                          act(r.txn_id, () => dismiss(r.txn_id))
                        }
                      >
                        Not a transfer
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
