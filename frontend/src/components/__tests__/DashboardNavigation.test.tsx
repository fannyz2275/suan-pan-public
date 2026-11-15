import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import Dashboard from '@/pages/Dashboard'
import { fetchFindingsCount, startFindingsReview } from '@/lib/findingsClient'

vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { email: 'test@example.com' }, signOut: vi.fn() }) }))
vi.mock('@/lib/api', () => ({
  default: { get: vi.fn(async (url: string) => ({ data: url === '/engine/cashflow' ? { cashflow: [{}] } : url === '/finance/accounts' || url === '/finance/goals' ? [] : {} })), patch: vi.fn(), delete: vi.fn() },
  fetchNetWorthTree: vi.fn().mockResolvedValue(null),
  fetchExpenseStatistic: vi.fn().mockResolvedValue(null),
}))
vi.mock('@/lib/findingsClient', () => ({ fetchFindingsCount: vi.fn().mockResolvedValue(0), startFindingsReview: vi.fn() }))
vi.mock('@/components/FinancialGrowth', () => ({ default: () => <div data-testid="FinancialGrowth">FinancialGrowth</div> }))
vi.mock('@/components/SpendingSummary', () => ({ default: () => <div data-testid="SpendingSummary">SpendingSummary</div> }))
vi.mock('@/components/GoalCard', () => ({ default: () => <div data-testid="GoalCard">GoalCard</div> }))
vi.mock('@/components/ForecastPanel', () => ({ default: () => <div data-testid="ForecastPanel">ForecastPanel</div> }))
vi.mock('@/components/ChatPanel', () => ({ default: () => <div data-testid="ChatPanel">ChatPanel</div> }))
vi.mock('@/components/UnifiedImportModal', () => ({ default: () => <div data-testid="UnifiedImportModal">UnifiedImportModal</div> }))
vi.mock('@/components/CategoryBaselineCard', () => ({ default: () => <div data-testid="CategoryBaselineCard">CategoryBaselineCard</div> }))
vi.mock('@/components/CategoryBreakdownTable', () => ({ default: () => <div data-testid="CategoryBreakdownTable">CategoryBreakdownTable</div> }))
vi.mock('@/components/RecurringCostsCard', () => ({ default: () => <div data-testid="RecurringCostsCard">RecurringCostsCard</div> }))
vi.mock('@/components/LearnedPoliciesCard', () => ({ default: () => <div data-testid="LearnedPoliciesCard">LearnedPoliciesCard</div> }))
vi.mock('@/components/AccountsCard', () => ({ default: () => <div data-testid="AccountsCard">AccountsCard</div> }))
vi.mock('@/components/ProfileCard', () => ({ default: () => <div data-testid="ProfileCard">ProfileCard</div> }))
vi.mock('@/components/TransferReviewBadge', () => ({ default: () => <div data-testid="TransferReviewBadge">TransferReviewBadge</div> }))
vi.mock('@/components/TransferReviewModal', () => ({ default: () => <div data-testid="TransferReviewModal">TransferReviewModal</div> }))
vi.mock('@/components/portfolio/PortfolioPage', () => ({ default: () => <div data-testid="PortfolioPage">PortfolioPage</div> }))

it('organizes features into the approved views while keeping the advisor mounted', async () => {
  render(<Dashboard />)
  await screen.findByTestId('FinancialGrowth')
  expect(screen.getByTestId('SpendingSummary')).toBeInTheDocument()
  expect(screen.queryByTestId('ProfileCard')).not.toBeInTheDocument()
  expect(screen.queryByTestId('GoalCard')).not.toBeInTheDocument()
  const advisor = screen.getByTestId('ChatPanel')
  expect(advisor).not.toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Open advisor' }))
  expect(advisor).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Close advisor' }))
  expect(advisor).not.toBeVisible()
  fireEvent.click(screen.getByTestId('tab-spending'))
  expect(screen.getByTestId('SpendingSummary')).toBeInTheDocument()
  expect(screen.getByTestId('RecurringCostsCard')).toBeInTheDocument()
  expect(screen.queryByTestId('LearnedPoliciesCard')).not.toBeInTheDocument()
  fireEvent.click(screen.getByTestId('tab-wealth'))
  expect(screen.getByTestId('AccountsCard')).toBeInTheDocument()
  fireEvent.click(screen.getByTestId('tab-portfolio'))
  expect(screen.getByTestId('PortfolioPage')).toBeInTheDocument()
  fireEvent.click(screen.getByTestId('tab-plan'))
  expect(screen.getByTestId('GoalCard')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('ForecastPanel')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: /^Settings$/ }))
  expect(screen.getByTestId('ProfileCard')).toBeInTheDocument()
  expect(screen.getByTestId('LearnedPoliciesCard')).toBeInTheDocument()
  expect(screen.getByTestId('ChatPanel')).toBe(advisor)
  fireEvent.click(screen.getByTestId('tab-overview'))
  expect(screen.getByTestId('SpendingSummary')).toBeInTheDocument()
})

it('does not start a hidden findings conversation on dashboard load', async () => {
  vi.mocked(fetchFindingsCount).mockResolvedValueOnce(2)
  render(<Dashboard />)
  await screen.findByTestId('FinancialGrowth')
  fireEvent.click(screen.getByRole('button', { name: 'Open advisor' }))
  await screen.findByRole('button', { name: 'Review 2 findings' })
  expect(startFindingsReview).not.toHaveBeenCalled()
})
