import { useEffect, useState } from 'react'
import api, { fetchCashFlowHistory } from './api'
import type { CashFlowPoint } from './types'

interface State {
  series: CashFlowPoint[]
  /** Index of the first projected month in `series` (the boundary). */
  todayIndex: number
  loading: boolean
  error: string | null
}

const EMPTY: State = { series: [], todayIndex: 0, loading: true, error: null }

export function useCashFlowSeries(refreshKey: number, months = 12): State {
  const [state, setState] = useState<State>(EMPTY)

  useEffect(() => {
    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState((s) => ({ ...s, loading: true, error: null }))
    Promise.all([
      fetchCashFlowHistory(months),
      api.get<{ cashflow: CashFlowPoint[] }>('/engine/cashflow', { params: { months } })
        .then((r) => r.data.cashflow),
    ])
      .then(([history, projection]) => {
        if (cancelled) return
        const series = [...history, ...projection]
        setState({
          series,
          todayIndex: history.length,
          loading: false,
          error: null,
        })
      })
      .catch((err) => {
        if (cancelled) return
        setState({ series: [], todayIndex: 0, loading: false, error: String(err) })
      })
    return () => { cancelled = true }
  }, [refreshKey, months])

  return state
}
