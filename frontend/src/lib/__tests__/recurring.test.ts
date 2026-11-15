import { expect, it, vi } from 'vitest'
import api from '@/lib/api'
import { runDetection } from '../recurring'

vi.mock('@/lib/api', () => ({ default: { post: vi.fn() } }))
it('bounds scan waiting time', async () => {
  vi.mocked(api.post).mockResolvedValue({ data: { rules: [] } })
  await expect(runDetection()).resolves.toEqual([])
  expect(api.post).toHaveBeenCalledWith('/engine/recurring/detect', undefined, { timeout: 45_000 })
})
