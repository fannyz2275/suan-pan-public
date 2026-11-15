import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCashFlowSeries } from '../useCashFlowSeries'
import { fetchCashFlowHistory } from '@/lib/api'
import api from '@/lib/api'

vi.mock('@/lib/api', () => ({
  default: { get: vi.fn() },
  fetchCashFlowHistory: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(fetchCashFlowHistory).mockReset()
  vi.mocked(api.get).mockReset()
})

describe('useCashFlowSeries', () => {
  it('concatenates history then projection in order, with todayIndex at boundary', async () => {
    vi.mocked(fetchCashFlowHistory).mockResolvedValue([
      { month: '2025-04', balance: 8000 },
      { month: '2025-05', balance: 8200 },
    ])
    vi.mocked(api.get).mockResolvedValue({
      data: { cashflow: [
        { month: '2026-05', balance: 8500 },
        { month: '2026-06', balance: 8700 },
      ] },
    } as { data: { cashflow: { month: string; balance: number }[] } })

    const { result } = renderHook(() => useCashFlowSeries(0))
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.series.map((p) => p.month)).toEqual([
      '2025-04', '2025-05', '2026-05', '2026-06',
    ])
    expect(result.current.todayIndex).toBe(2)
  })

  it('exposes loading=true while either fetch is pending', async () => {
    let resolveHist!: (v: { month: string; balance: number }[]) => void
    vi.mocked(fetchCashFlowHistory).mockReturnValue(
      new Promise((resolve) => { resolveHist = resolve })
    )
    vi.mocked(api.get).mockResolvedValue({ data: { cashflow: [] } } as { data: { cashflow: { month: string; balance: number }[] } })

    const { result } = renderHook(() => useCashFlowSeries(0))
    expect(result.current.loading).toBe(true)
    resolveHist([])
    await waitFor(() => expect(result.current.loading).toBe(false))
  })

  it('refetches when refreshKey changes', async () => {
    vi.mocked(fetchCashFlowHistory).mockResolvedValue([])
    vi.mocked(api.get).mockResolvedValue({ data: { cashflow: [] } } as { data: { cashflow: { month: string; balance: number }[] } })

    const { rerender } = renderHook(({ k }: { k: number }) => useCashFlowSeries(k), {
      initialProps: { k: 0 },
    })
    await waitFor(() => expect(fetchCashFlowHistory).toHaveBeenCalledTimes(1))
    rerender({ k: 1 })
    await waitFor(() => expect(fetchCashFlowHistory).toHaveBeenCalledTimes(2))
  })
})
