import { useEffect, useState } from 'react'
import { fetchReview } from '@/lib/transfers'

interface Props {
  onClick: () => void
  refreshKey: number
}

export default function TransferReviewBadge({ onClick, refreshKey }: Props) {
  const [count, setCount] = useState(0)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    // Badge reflects all flagged transfers, not just the 90d window,
    // so the user can always find the entry point.
    fetchReview('all')
      .then((rows) => {
        if (!cancelled) {
          setCount(rows.length)
          setError(false)
        }
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  if (count <= 0 && !error) return null

  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
    >
      {error ? <span>Transfer review unavailable</span> : <><span>{count}</span><span>to review</span></>}
    </button>
  )
}
