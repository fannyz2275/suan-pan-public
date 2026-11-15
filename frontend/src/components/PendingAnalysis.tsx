import { Play, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'

export interface PendingAnalysisState {
  id: string
  ready: boolean
  requirements: string[]
  missing: string[]
  upload_action: string | null
}

const labels: Record<string, string> = {
  aligned_wealth: 'Month-end balances for all accounts',
  complete_cost_basis: 'Purchase costs for your holdings',
  period_security_returns: 'Investment values and activity for the comparison period',
  peer_benchmark: 'A comparable peer dataset',
  verified_refund_data: 'Verified refund details',
}

export default function PendingAnalysis({ pending, busy, onContinue, onUpload }: {
  pending: PendingAnalysisState | null; busy: boolean; onContinue: () => void; onUpload?: () => void
}) {
  if (!pending) return null
  return <div className="border-t px-4 py-3 text-sm" data-testid="pending-analysis">
    {pending.ready ? <>
      <p className="mb-2">Your data was updated.</p>
      <Button size="sm" disabled={busy} onClick={onContinue}><Play size={14} />Continue analysis</Button>
    </> : <>
      <p className="mb-2">Still needed: {(pending.missing ?? pending.requirements).map(k => labels[k] ?? 'Additional evidence').join('; ')}.</p>
      {pending.upload_action === 'upload_statements' && onUpload && <Button size="sm" disabled={busy} onClick={onUpload}><Upload size={14} />Upload missing statements</Button>}
    </>}
  </div>
}
