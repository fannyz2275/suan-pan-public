import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Pencil } from 'lucide-react'
import { listRules, patchRule, runDetection, type Frequency, type RecurringRule } from '@/lib/recurring'

const frequencies: Frequency[] = ['weekly', 'biweekly', 'semi_monthly', 'monthly', 'quarterly', 'semi_annual', 'annual']

function formatFrequency(freq: string) {
  return ({ weekly: 'Weekly', biweekly: 'Bi-weekly', semi_monthly: 'Twice a month',
    monthly: 'Monthly', quarterly: 'Quarterly', semi_annual: 'Every six months', annual: 'Annually' } as Record<string, string>)[freq] ?? freq.replace(/_/g, ' ')
}

function lastPayment(value: string | null) {
  if (!value) return 'Latest payment unavailable'
  const date = new Date(`${value}T12:00:00`)
  if (Number.isNaN(date.getTime())) return 'Latest payment unavailable'
  return `Last paid ${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
}

function RuleRow({ rule, onRemove, onFrequency }: { rule: RecurringRule; onRemove: (id: string) => void; onFrequency: (id: string, frequency: Frequency) => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  return (
    <div className="flex items-start justify-between gap-3 py-2 text-sm">
      <div className="flex-1 min-w-0 break-words">
        <p className="font-medium">{rule.keyword}</p>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          {editing ? <select aria-label={`Frequency for ${rule.keyword}`} value={rule.frequency} disabled={saving}
            className="max-w-full border rounded px-1 py-1 bg-background text-foreground"
            onChange={async e => { setSaving(true); try { await onFrequency(rule.id, e.target.value as Frequency); setEditing(false) } finally { setSaving(false) } }}>
            {frequencies.map(f => <option key={f} value={f}>{formatFrequency(f)}</option>)}
          </select> : <span>{formatFrequency(rule.frequency)}</span>}
          <Button size="icon" variant="ghost" className="size-6" title="Change frequency" aria-label={`Change frequency for ${rule.keyword}`} onClick={() => setEditing(v => !v)} disabled={saving}><Pencil className="size-3" /></Button>
        </div>
        <p className="text-xs text-muted-foreground">{lastPayment(rule.last_seen_date)}</p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <span className="tabular-nums" title="Typical amount per payment">${rule.amount_median.toFixed(2)}</span>
        <Button variant="ghost" size="sm" onClick={() => onRemove(rule.id)}>
          Remove
        </Button>
      </div>
    </div>
  )
}

type ScanStatus =
  | { kind: 'idle' }
  | {
      kind: 'ok'
      newCount: number
      existingCount: number
      pendingCount: number
      proposedCount: number
    }
  | { kind: 'error'; message: string }

export default function RecurringCostsCard() {
  const [rules, setRules] = useState<RecurringRule[]>([])
  const [scanning, setScanning] = useState(false)
  const [slow, setSlow] = useState(false)
  const [sinceMonth, setSinceMonth] = useState('')
  const scanInFlight = useRef(false)
  const loadVersion = useRef(0)
  const [scanStatus, setScanStatus] = useState<ScanStatus>({ kind: 'idle' })

  const load = () => {
    const version = ++loadVersion.current
    listRules().then(rows => {
      if (version === loadVersion.current) { setRules(rows); setScanStatus({ kind: 'idle' }) }
    }).catch(() => {
      if (version === loadVersion.current) setScanStatus({ kind: 'error', message: 'Could not load recurring payments. Refresh results to try again.' })
    })
  }

  useEffect(() => { load() }, [])
  useEffect(() => {
    if (!scanning) return
    const timer = setTimeout(() => setSlow(true), 8000)
    return () => clearTimeout(timer)
  }, [scanning])

  const handleScan = async () => {
    if (scanInFlight.current) return
    scanInFlight.current = true
    loadVersion.current++
    setScanning(true)
    setSlow(false)
    setScanStatus({ kind: 'idle' })
    try {
      const beforeIds = new Set(rules.map((r) => r.id))
      const after = await runDetection()
      const newCount = after.filter((r) => !beforeIds.has(r.id)).length
      const existingCount = after.length - newCount
      const pendingCount = after.filter((r) => r.status === 'pending_review').length
      const proposedCount = after.filter((r) => r.status === 'proposed').length
      setScanStatus({ kind: 'ok', newCount, existingCount, pendingCount, proposedCount })
      // runDetection already returns the full post-scan list; set it directly
      // so there's no flicker and no risk of a race with a follow-up listRules.
      setRules(after)
    } catch (e) {
      console.error('recurring scan failed', e)
      const timeout = e instanceof Error && 'code' in e && (e.code === 'ECONNABORTED' || e.code === 'ETIMEDOUT')
      const message = timeout
        ? 'The scan is taking longer than expected. It may still finish on the server. Refresh results shortly to check.'
        : "We couldn't confirm the scan completed. Refresh results to check for updated payments, or try scanning again."
      setScanStatus({ kind: 'error', message })
    } finally {
      setScanning(false)
      scanInFlight.current = false
    }
  }

  const handleRemove = async (id: string) => {
    try {
      await patchRule(id, { action: 'reject' })
      setRules((prev) => prev.filter((r) => r.id !== id))
    } catch {
      /* noop */
    }
  }

  const handleFrequency = async (id: string, frequency: Frequency) => {
    try {
      const updated = await patchRule(id, { action: 'edit', frequency })
      setRules(prev => prev.map(rule => rule.id === id ? updated : rule))
    } catch {
      setScanStatus({kind:'error', message:'Could not save the frequency. Your previous schedule is unchanged.'})
    }
  }

  const pending = rules.filter((r) => r.status === 'pending_review')
  const active = rules.filter((r) => (r.status === 'user_confirmed' || r.status === 'auto_applied')
    && (!sinceMonth || !r.last_seen_date || r.last_seen_date >= `${sinceMonth}-01`))
  const income = active.filter((r) => r.direction === 'income')
  const expenses = active.filter((r) => r.direction === 'expense')

  return (
    <section className="border-t pt-4 space-y-4" aria-label="Current recurring rules">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="font-medium">Recurring payments</h3>
          {pending.length > 0 && (
            <Badge variant="secondary">{pending.length} to review</Badge>
          )}
        </div>
        <Button size="sm" onClick={handleScan} disabled={scanning}>
          {scanning ? 'Scanning…' : 'Scan transactions'}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label htmlFor="recurring-since">Hide payments last seen before</label>
        <input id="recurring-since" type="month" value={sinceMonth} onChange={e => setSinceMonth(e.target.value)} className="min-w-0 border rounded px-2 py-1 bg-background" />
        {sinceMonth && <Button variant="ghost" size="sm" onClick={() => setSinceMonth('')}>Show all dates</Button>}
      </div>
      {scanning && <p role="status" className="text-xs text-muted-foreground">{slow ? 'Still checking your transactions. Saved payments remain available below.' : 'Checking recorded transactions...'}</p>}
      {scanStatus.kind === 'ok' && (
        <div className="text-xs text-muted-foreground -mt-2 space-y-0.5">
          <p>
            {scanStatus.newCount > 0
              ? `Scan complete · ${scanStatus.newCount} new · ${scanStatus.existingCount} existing.`
              : 'Scan complete · no new patterns found.'}
          </p>
          {(scanStatus.pendingCount > 0 || scanStatus.proposedCount > 0) && (
            <p>
              {scanStatus.pendingCount > 0 && `${scanStatus.pendingCount} awaiting review · `}
              {scanStatus.proposedCount > 0 && `${scanStatus.proposedCount} below confidence threshold (${scanStatus.proposedCount === 1 ? 'likely' : 'each likely'} needs more history or has inconsistent descriptions)`}
            </p>
          )}
          {scanStatus.newCount === 0 && scanStatus.proposedCount === 0 && scanStatus.pendingCount === 0 && (
            <p>Monthly bills need ≥3 months of matching description/amount to detect.</p>
          )}
        </div>
      )}
      {scanStatus.kind === 'error' && (
        <div role="alert" className="text-xs text-destructive space-y-1"><p>{scanStatus.message}</p><Button variant="outline" size="sm" onClick={load} disabled={scanning}>Refresh results</Button></div>
      )}

      <div className="space-y-3">
        <div>
          <h4 className="text-sm font-medium mb-1">Income</h4>
          {income.length === 0 ? (
            <p className="text-sm text-muted-foreground">{sinceMonth ? 'None in this date range.' : 'None yet.'}</p>
          ) : (
            <div className="divide-y">
              {income.map((r) => (
                <RuleRow key={r.id} rule={r} onRemove={handleRemove} onFrequency={handleFrequency} />
              ))}
            </div>
          )}
        </div>

        <div>
          <h4 className="text-sm font-medium mb-1">Expenses</h4>
          {expenses.length === 0 ? (
            <p className="text-sm text-muted-foreground">{sinceMonth ? 'None in this date range.' : 'None yet.'}</p>
          ) : (
            <div className="divide-y">
              {expenses.map((r) => (
                <RuleRow key={r.id} rule={r} onRemove={handleRemove} onFrequency={handleFrequency} />
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
