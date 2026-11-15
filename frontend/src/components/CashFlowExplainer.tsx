import { useEffect, useState } from 'react'
import { requestCashFlowExplanation, type CashFlowExplainPayload } from '@/lib/api'

interface Props {
  payload: CashFlowExplainPayload
  refreshKey: number
}

export default function CashFlowExplainer({ payload, refreshKey }: Props) {
  const [explanation, setExplanation] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Invalidate cached explanation whenever refreshKey changes.
  useEffect(() => {
    setExplanation(null)
  }, [refreshKey])

  const reveal = async () => {
    if (loading || explanation !== null) return
    setLoading(true)
    try {
      const text = await requestCashFlowExplanation(payload)
      setExplanation(text)
    } catch {
      setExplanation('Could not generate explanation right now.')
    } finally {
      setLoading(false)
    }
  }

  if (explanation !== null) {
    return <p className="text-xs text-muted-foreground mt-2 leading-relaxed">{explanation}</p>
  }
  return (
    <button
      type="button"
      onClick={reveal}
      disabled={loading}
      className="text-xs text-muted-foreground underline hover:text-foreground mt-2"
    >
      {loading ? 'Generating…' : 'How is this calculated?'}
    </button>
  )
}
