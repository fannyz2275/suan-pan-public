import api from './api'

/** One notch on a 1-5 identity slider. Mirrors the backend Anchor TypedDict
 *  in app/profile/scales.py — keep the two in sync. */
export interface ScaleAnchor {
  value: number
  label: string
  description: string
}

export interface ScalesPayload {
  risk_tolerance: ScaleAnchor[]
  time_horizon: ScaleAnchor[]
}

let _cache: ScalesPayload | null = null
let _inflight: Promise<ScalesPayload> | null = null

/** Fetch the 1-5 anchor sentences. Cached for the lifetime of the app —
 *  the data is static UX copy that doesn't change at runtime. */
export async function fetchScales(): Promise<ScalesPayload> {
  if (_cache) return _cache
  if (_inflight) return _inflight
  _inflight = api.get<ScalesPayload>('/profile/scales').then(({ data }) => {
    _cache = data
    _inflight = null
    return data
  }).catch((e) => {
    _inflight = null
    throw e
  })
  return _inflight
}

/** Test-only reset for cache between assertions. */
export function _resetScalesCache(): void {
  _cache = null
  _inflight = null
}
