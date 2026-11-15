import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import LookThroughTopHoldings from '../portfolio/LookThroughTopHoldings'
import PortfolioTimeSeriesChart from '../portfolio/PortfolioTimeSeriesChart'
import { fetchLookThrough, fetchTimeSeries } from '../../lib/portfolio'

vi.mock('../../lib/portfolio', () => ({
  fetchLookThrough: vi.fn(),
  fetchTimeSeries: vi.fn(),
}))
vi.mock('recharts', () => ({
  ResponsiveContainer: () => null,
  CartesianGrid: () => null,
  Line: () => null,
  LineChart: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}))

beforeEach(() => vi.resetAllMocks())

it('clears an account error and shows loading when switching accounts', async () => {
  vi.mocked(fetchLookThrough).mockRejectedValueOnce(new Error('failed'))
  const { rerender } = render(<LookThroughTopHoldings accountId="first" />)
  await screen.findByText('Could not load look-through holdings.')
  vi.mocked(fetchLookThrough).mockReturnValueOnce(new Promise(() => {}))
  rerender(<LookThroughTopHoldings accountId="second" />)
  expect(screen.getByTestId('lookthrough-loading')).toBeInTheDocument()
  expect(screen.queryByText('Could not load look-through holdings.')).not.toBeInTheDocument()
  expect(fetchLookThrough).toHaveBeenLastCalledWith(10, 'second')
})

it('shows a chart request failure instead of an empty portfolio message', async () => {
  vi.mocked(fetchTimeSeries).mockRejectedValueOnce(new Error('failed'))
  render(<PortfolioTimeSeriesChart fromDate="2026-01-01" toDate="2026-02-01" />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load portfolio values.')
  expect(screen.queryByText(/No snapshots in this window/)).not.toBeInTheDocument()
})

it('recovers from a chart failure after the date window changes', async () => {
  vi.mocked(fetchTimeSeries).mockRejectedValueOnce(new Error('failed'))
  const { rerender } = render(<PortfolioTimeSeriesChart fromDate="2026-01-01" toDate="2026-02-01" />)
  await screen.findByRole('alert')
  vi.mocked(fetchTimeSeries).mockResolvedValueOnce({ series: [], overlays: [] })
  rerender(<PortfolioTimeSeriesChart fromDate="2026-01-15" toDate="2026-02-01" />)
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(await screen.findByText(/No snapshots in this window/)).toBeInTheDocument()
})
