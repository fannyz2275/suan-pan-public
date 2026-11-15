import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mock the api module before importing profileScales — the import-time
// supabase URL check fails in tests otherwise.
vi.mock('@/lib/api', () => ({
  default: {
    get: vi.fn(),
  },
}))

import api from '@/lib/api'
import { fetchScales, _resetScalesCache } from '../profileScales'

const STUB_PAYLOAD = {
  risk_tolerance: [
    { value: 1, label: 'capital preservation', description: 'a' },
    { value: 5, label: 'high conviction', description: 'b' },
  ],
  time_horizon: [
    { value: 1, label: '<1 year', description: 'c' },
    { value: 5, label: '>6 years', description: 'd' },
  ],
}


beforeEach(() => {
  _resetScalesCache()
  vi.clearAllMocks()
})


describe('fetchScales', () => {
  it('fetches once on cold start and caches the result', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: STUB_PAYLOAD })

    const a = await fetchScales()
    const b = await fetchScales()

    expect(api.get).toHaveBeenCalledTimes(1)
    expect(a).toEqual(STUB_PAYLOAD)
    expect(b).toBe(a)  // identity-equal — same cached object
  })

  it('de-dupes parallel callers into one in-flight request', async () => {
    let resolve!: (v: { data: typeof STUB_PAYLOAD }) => void
    vi.mocked(api.get).mockImplementation(
      () => new Promise((r) => { resolve = r }),
    )

    const p1 = fetchScales()
    const p2 = fetchScales()
    const p3 = fetchScales()

    expect(api.get).toHaveBeenCalledTimes(1)
    resolve({ data: STUB_PAYLOAD })

    const [r1, r2, r3] = await Promise.all([p1, p2, p3])
    expect(r1).toBe(r2)
    expect(r2).toBe(r3)
  })

  it('does not cache failed requests; allows retry', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('network'))
    await expect(fetchScales()).rejects.toThrow('network')

    vi.mocked(api.get).mockResolvedValueOnce({ data: STUB_PAYLOAD })
    const ok = await fetchScales()
    expect(ok).toEqual(STUB_PAYLOAD)
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('_resetScalesCache forces the next call to refetch', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: STUB_PAYLOAD })
    await fetchScales()
    expect(api.get).toHaveBeenCalledTimes(1)

    _resetScalesCache()
    await fetchScales()
    expect(api.get).toHaveBeenCalledTimes(2)
  })
})
