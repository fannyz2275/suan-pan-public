import AIProvidersCard from '@/components/AIProvidersCard'
import { useCallback, useEffect, useRef, useState } from 'react'
import { MessageCircle, Settings, X } from 'lucide-react'
import type { AdvisorContext } from '@/lib/advisorContext'
import { useAuth } from '@/contexts/AuthContext'
import api, { fetchNetWorthTree, fetchExpenseStatistic, type ExpenseStatistic } from '@/lib/api'
import { fetchFindingsCount, startFindingsReview } from '@/lib/findingsClient'
import FinancialGrowth from '@/components/FinancialGrowth'
import SpendingSummary from '@/components/SpendingSummary'
import GoalCard from '@/components/GoalCard'
import ForecastPanel from '@/components/ForecastPanel'
import ChatPanel from '@/components/ChatPanel'
import UnifiedImportModal from '@/components/UnifiedImportModal'
import ImportToastProvider from '@/components/ImportToastProvider'
import PortfolioPage from '@/components/portfolio/PortfolioPage'
import RecurringCostsCard from '@/components/RecurringCostsCard'
import LearnedPoliciesCard from '@/components/LearnedPoliciesCard'
import AccountsCard from '@/components/AccountsCard'
import ProfileCard, { type Profile, type Memory } from '@/components/ProfileCard'
import TransferReviewBadge from '@/components/TransferReviewBadge'
import TransferReviewModal from '@/components/TransferReviewModal'
import { Button } from '@/components/ui/button'
import type { Account, Goal, NetWorthNode, Snapshot } from '@/lib/types'

export default function Dashboard() {
  const { user, signOut } = useAuth()
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [tree, setTree] = useState<NetWorthNode | null>(null)
  const [goals, setGoals] = useState<Goal[]>([])
  useEffect(() => {
    const open = () => { setActiveTab('settings'); setShowImport(false) }
    window.addEventListener('open-ai-providers', open)
    return () => window.removeEventListener('open-ai-providers', open)
  }, [])
  const [profile, setProfile] = useState<Profile>({ id: '' })
  const [memory, setMemory] = useState<Memory | null>(null)
  const [showImport, setShowImport] = useState(false)
  const [activeTab, setActiveTab] = useState<'overview' | 'spending' | 'wealth' | 'plan' | 'settings'>('overview')
  const [wealthTab, setWealthTab] = useState<'accounts' | 'portfolio'>('accounts')
  const [advisorOpen, setAdvisorOpen] = useState(false)
  const [findingsCount, setFindingsCount] = useState(0)
  const [startingReview, setStartingReview] = useState(false)
  const [reviewError, setReviewError] = useState(false)
  const [advisorContext, setAdvisorContext] = useState<AdvisorContext | null>(null)
  const advisorTrigger = useRef<HTMLElement | null>(null)
  const closeAdvisorButton = useRef<HTMLButtonElement>(null)
  const openAdvisor = (context?: AdvisorContext) => {
    advisorTrigger.current = document.activeElement as HTMLElement
    if (context) setAdvisorContext(context)
    setAdvisorOpen(true)
  }
  const closeAdvisor = () => {
    setAdvisorOpen(false)
    advisorTrigger.current?.focus()
  }
  useEffect(() => {
    if (advisorOpen) closeAdvisorButton.current?.focus()
  }, [advisorOpen])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [reviewOpen, setReviewOpen] = useState(false)
  const [reviewRefresh, setReviewRefresh] = useState(0)
  const [expenseStatistic, setExpenseStatistic] = useState<ExpenseStatistic | null>(null)

  const refresh = useCallback(() => {
    api.get('/engine/snapshot').then((r) => setSnapshot(r.data)).catch(() => {})
    fetchNetWorthTree().then(setTree).catch(() => setTree(null))
    api.get('/finance/goals').then((r) => setGoals(r.data)).catch(() => {})
    api.get('/finance/accounts').then((r) => setAccounts(r.data)).catch(() => {})
    api.get('/profile').then((r) => setProfile(r.data)).catch(() => {})
    api.get('/profile/memory').then((r) => setMemory(r.data)).catch(() => {})
    fetchExpenseStatistic().then(setExpenseStatistic).catch(() => setExpenseStatistic(null))
    // Bump the refresh key so transaction-backed widgets (CashFlowChart,
    // TransactionChart, TransferReviewBadge) refetch too. Any user action
    // that triggers a refresh — account edit, import, chat tool call —
    // should invalidate ALL data-displaying widgets on the page.
    setReviewRefresh((k) => k + 1)
  }, [])

  const saveProfile = useCallback(async (patch: Partial<Profile>) => {
    const { data } = await api.patch('/profile', patch)
    setProfile(data)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // Refetch when the user comes back to the tab. The browser keeps the
  // page mounted in the background, but the data on screen can be hours
  // stale by the time they return — auto-refresh on visibility avoids the
  // "I have to hit reload" UX. Cooldown of 30s prevents thrash on rapid
  // tab switching.
  useEffect(() => {
    let lastRefresh = Date.now()
    const handler = () => {
      if (document.visibilityState !== 'visible') return
      const since = Date.now() - lastRefresh
      if (since < 30_000) return
      lastRefresh = Date.now()
      refresh()
    }
    document.addEventListener('visibilitychange', handler)
    return () => document.removeEventListener('visibilitychange', handler)
  }, [refresh])

  useEffect(() => {
    if (sessionStorage.getItem('findings-snoozed') === '1') return
    let cancelled = false
    ;(async () => {
      try {
        const count = await fetchFindingsCount()
        if (!cancelled) setFindingsCount(count)
      } catch {
        // Silent: a failed auto-prompt should never block the dashboard.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <ImportToastProvider>
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b px-4 sm:px-6 py-3 flex flex-wrap gap-3 items-center justify-between">
        <h1 className="font-semibold text-lg">算盘</h1>
        <div className="flex flex-wrap items-center gap-3">
          <TransferReviewBadge
            onClick={() => setReviewOpen(true)}
            refreshKey={reviewRefresh}
          />
          <Button variant="outline" size="sm" onClick={() => setShowImport(true)}>
            + Import statements
          </Button>
          <span className="text-sm text-muted-foreground max-w-48 truncate">{user?.email}</span>
          <Button variant="outline" size="sm" aria-label="Open advisor" aria-expanded={advisorOpen} aria-controls="advisor-panel" onClick={() => openAdvisor()}><MessageCircle size={16} />Advisor</Button>
          <Button variant="ghost" size="sm" aria-label="Settings" title="Settings" aria-pressed={activeTab === 'settings'} onClick={() => setActiveTab('settings')}><Settings size={18} /></Button>
          <Button variant="ghost" size="sm" onClick={signOut}>Sign out</Button>
        </div>
      </header>

      <div className={`max-w-6xl mx-auto p-4 sm:p-6 grid grid-cols-1 gap-6 ${advisorOpen ? 'lg:grid-cols-[minmax(0,1fr)_24rem]' : ''}`}>
        {/* Left column: main dashboard */}
        <div className="min-w-0 space-y-4">
          {/* Tab bar */}
          <nav aria-label="Main navigation" className="flex gap-1 border-b overflow-x-auto">
            {(['overview', 'spending', 'wealth', 'plan'] as const).map((tab) => (
              <button
                key={tab}
                data-testid={`tab-${tab}`}
                onClick={() => setActiveTab(tab)}
                aria-current={activeTab === tab ? 'page' : undefined}
                className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors capitalize ${
                  activeTab === tab
                    ? 'border-primary text-primary'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </nav>

          {/* Tab content */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              <SpendingSummary refreshKey={reviewRefresh} onExplain={openAdvisor} />
              {snapshot ? (
                <FinancialGrowth refreshKey={reviewRefresh} onExplain={openAdvisor} />
              ) : (
                <div className="rounded-lg border p-6 space-y-3">
                  <p className="text-sm text-muted-foreground">No accounts yet.</p>
                  <Button size="sm" onClick={() => setShowImport(true)}>
                    Import statements to get started
                  </Button>
                </div>
              )}
            </div>
          )}

          {activeTab === 'plan' && (
            <div className="space-y-6">
              <ForecastPanel refreshKey={reviewRefresh} />
              <GoalCard goals={goals} onChanged={refresh} />
            </div>
          )}

          {activeTab === 'wealth' && (
            <div className="space-y-4">
              <nav aria-label="Wealth navigation" className="flex gap-1 border-b">
                {(['accounts', 'portfolio'] as const).map(tab => <button key={tab} data-testid={`tab-${tab}`} aria-current={wealthTab === tab ? 'page' : undefined} onClick={() => setWealthTab(tab)} className={`px-3 py-2 text-sm border-b-2 capitalize ${wealthTab === tab ? 'border-primary text-primary' : 'border-transparent text-muted-foreground'}`}>{tab}</button>)}
              </nav>
              {wealthTab === 'accounts' ? <AccountsCard accounts={accounts} tree={tree} onRefresh={refresh} /> : <PortfolioPage />}
            </div>
          )}

          {activeTab === 'spending' && (
            <div className="space-y-6">
              <SpendingSummary refreshKey={reviewRefresh} detailed onExplain={openAdvisor} />
              <RecurringCostsCard />
            </div>
          )}
          {activeTab === 'settings' && (
            <div className="space-y-6">
              <h2 className="text-base font-semibold">Settings</h2>
              <AIProvidersCard />
              <ProfileCard profile={profile} memory={memory} onSave={saveProfile} statistic={expenseStatistic} onClearMemory={async () => {
                await api.delete('/profile/memory')
                setMemory(null)
              }} />
              <LearnedPoliciesCard />
            </div>
          )}
        </div>

        {/* Keep the advisor mounted so hiding it preserves drafts and streams. */}
        <aside id="advisor-panel" aria-label="Financial advisor" style={{ display: advisorOpen ? undefined : 'none' }} className="min-w-0 order-first lg:order-last" onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); closeAdvisor() } }}>
          <div className="sticky top-6">
            <div
              className="rounded-lg border overflow-hidden flex flex-col min-h-0"
              style={{ height: 'min(44rem, calc(100dvh - 7rem))' }}
            >
              <div className="shrink-0 px-4 py-2 border-b font-medium text-sm flex items-center justify-between">
                Financial Advisor
                <button className="text-xs underline" onClick={() => { setActiveTab('settings'); closeAdvisor() }}>AI provider settings</button>
                <button ref={closeAdvisorButton} aria-label="Close advisor" title="Close advisor" onClick={closeAdvisor} className="p-1"><X size={18} /></button>
              </div>
              {findingsCount > 0 && <div className="px-3 py-2 border-b">
                <Button size="sm" variant="outline" disabled={startingReview} onClick={async () => {
                  setStartingReview(true)
                  setReviewError(false)
                  try {
                    const res = await startFindingsReview()
                    if (!res) throw new Error('Review unavailable')
                    window.dispatchEvent(new CustomEvent('findings-review-started', { detail: res.session_id }))
                    setFindingsCount(0)
                  } catch { setReviewError(true) }
                  finally { setStartingReview(false) }
                }}>{startingReview ? 'Starting review...' : `Review ${findingsCount} findings`}</Button>
                {reviewError && <p role="alert" className="text-xs mt-2">Could not start review. Try again.</p>}
              </div>}
              <ChatPanel className="flex-1 min-h-0" onChanged={refresh} active={advisorOpen} context={advisorContext} onClearContext={() => setAdvisorContext(null)} onRequestUpload={() => setShowImport(true)} importRevision={reviewRefresh} />
            </div>
          </div>
        </aside>
      </div>

      {showImport && (
        <UnifiedImportModal
          onClose={() => setShowImport(false)}
          onImported={() => {
            refresh()
            setReviewRefresh((k) => k + 1)
          }}
          onRequestReview={() => setReviewOpen(true)}
        />
      )}

      <TransferReviewModal
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        onChanged={refresh}
        onRequestUpload={() => {
          setReviewOpen(false)
          setShowImport(true)
        }}
      />
    </div>
    </ImportToastProvider>
  )
}
