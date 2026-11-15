import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { postFindingDecision, type FindingKind } from '@/lib/findingsClient'

interface Props {
  id: string
  kind: FindingKind
  body: string
  onDecided: (verdict: 'accept' | 'reject', label: string) => void
}

export default function FindingCard({ id, kind, body, onDecided }: Props) {
  const [verdict, setVerdict] = useState<'accept' | 'reject' | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const decide = async (decision: 'accept' | 'reject') => {
    if (busy || verdict) return
    setBusy(true)
    setErr(null)
    try {
      await postFindingDecision(kind, id, decision)
      setVerdict(decision)
      onDecided(decision, body.split('\n')[0].slice(0, 80))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border rounded-md p-2 my-1.5 bg-background/60">
      <div className="text-xs whitespace-pre-wrap">{body}</div>
      {verdict ? (
        <div className="mt-1.5 text-xs text-muted-foreground">
          {verdict === 'accept' ? '✓ Confirmed' : '✗ Rejected'}
        </div>
      ) : (
        <div className="mt-1.5 flex gap-1.5">
          <Button size="sm" className="h-6 px-2 text-xs" onClick={() => decide('accept')} disabled={busy}>
            Accept
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-6 px-2 text-xs"
            onClick={() => decide('reject')}
            disabled={busy}
          >
            Reject
          </Button>
        </div>
      )}
      {err && <div className="mt-1 text-xs text-red-600">{err}</div>}
    </div>
  )
}
