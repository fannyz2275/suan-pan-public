import { useCallback, useEffect, useState } from 'react'
import {
  type Domain,
  type LearnedOverride,
  type LearnedResponse,
  describeOverride,
  fetchLearnedPolicies,
  forgetOverride,
} from '@/lib/policy'
import { type UserNote, fetchUserNotes, forgetNote } from '@/lib/notes'

const DOMAIN_LABEL: Record<Domain, string> = {
  categorize: 'Categorization',
  transfers: 'Transfers',
  recurring: 'Recurring',
  feasibility: 'Feasibility',
  baseline: 'Baseline',
}

function relativeTime(iso: string): string {
  // Avoid pulling in a date lib; "n days ago" / "today" / "yesterday" is plenty.
  const then = new Date(iso).getTime()
  const days = Math.floor((Date.now() - then) / (1000 * 60 * 60 * 24))
  if (Number.isNaN(days)) return ''
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  if (days < 365) return `${Math.floor(days / 30)}mo ago`
  return `${Math.floor(days / 365)}y ago`
}

/** "What Suan-Pan has learned" — read-only audit + one-click forget for
 * every per-user policy that biases the engine's behavior. Renders the
 * pgvector-light, ranking-light view: domain → human description → forget.
 *
 * Empty state ("nothing learned yet") is the common case for new users
 * and is intentionally cheerful rather than apologetic. */
export default function LearnedPoliciesCard() {
  const [data, setData] = useState<LearnedResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [pendingForget, setPendingForget] = useState<Set<string>>(new Set())

  // Notes state — independent of overrides state
  const [notes, setNotes] = useState<UserNote[]>([])
  const [notesLoading, setNotesLoading] = useState(true)
  const [notesError, setNotesError] = useState<string | null>(null)
  const [pendingForgetNote, setPendingForgetNote] = useState<Set<string>>(new Set())

  const refresh = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const next = await fetchLearnedPolicies()
      setData(next)
    } catch (e) {
      setError((e as Error).message ?? 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  const refreshNotes = useCallback(async () => {
    try {
      setNotesLoading(true)
      setNotesError(null)
      const next = await fetchUserNotes()
      setNotes(next)
    } catch (e) {
      setNotesError((e as Error).message ?? 'Failed to load')
    } finally {
      setNotesLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => { void refreshNotes() }, [refreshNotes])

  const handleForget = useCallback(
    async (id: string) => {
      setPendingForget((prev) => new Set(prev).add(id))
      try {
        await forgetOverride(id)
        // Optimistic remove — the next refresh would also clear it, but
        // we don't wait so the click feels instant.
        setData((prev) =>
          prev
            ? { ...prev, overrides: prev.overrides.filter((o) => o.id !== id) }
            : prev,
        )
      } catch (e) {
        setError((e as Error).message ?? 'Failed to forget')
      } finally {
        setPendingForget((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      }
    },
    [],
  )

  const handleForgetNote = useCallback(
    async (id: string) => {
      setPendingForgetNote((prev) => new Set(prev).add(id))
      try {
        await forgetNote(id)
        // Optimistic remove
        setNotes((prev) => prev.filter((n) => n.id !== id))
      } catch (e) {
        setNotesError((e as Error).message ?? 'Failed to forget')
      } finally {
        setPendingForgetNote((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      }
    },
    [],
  )

  const overrides = data?.overrides ?? []
  const grouped = overrides.reduce<Record<Domain, LearnedOverride[]>>(
    (acc, o) => {
      ;(acc[o.domain] ||= []).push(o)
      return acc
    },
    { categorize: [], transfers: [], recurring: [], feasibility: [], baseline: [] },
  )

  const preferences = notes.filter((n) => n.kind === 'preference')
  const facts = notes.filter((n) => n.kind === 'fact')

  return (
    <div className="border rounded-lg p-4 space-y-4">
      <div className="flex items-baseline justify-between">
        <h3 className="font-medium text-sm">What Suan-Pan has learned</h3>
        <button
          type="button"
          onClick={() => void refresh()}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          refresh
        </button>
      </div>

      {/* ── Overrides section ── */}
      {loading && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}
      {!loading && error && (
        <p className="text-sm text-red-600">{error}</p>
      )}
      {!loading && !error && overrides.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Nothing learned yet. Suan-Pan picks up your preferences as you
          recategorize, mark transfers as external, or reject recurring
          suggestions.
        </p>
      )}
      {!loading && !error && (Object.keys(grouped) as Domain[]).map((d) => {
        const rows = grouped[d]
        if (!rows.length) return null
        return (
          <section key={d}>
            <h4 className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
              {DOMAIN_LABEL[d]}
            </h4>
            <ul className="divide-y border rounded">
              {rows.map((o) => {
                const isPending = pendingForget.has(o.id)
                return (
                  <li
                    key={o.id}
                    className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{describeOverride(o)}</div>
                      <div className="text-xs text-muted-foreground">
                        reinforced {relativeTime(o.last_reinforced_at)} ·
                        strength {o.strength}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleForget(o.id)}
                      disabled={isPending}
                      className="text-xs px-2 py-1 rounded border hover:bg-muted disabled:opacity-50"
                    >
                      {isPending ? 'forgetting…' : 'forget'}
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        )
      })}

      {/* ── Separator ── */}
      <hr className="border-border" />

      {/* ── Notes section ── */}
      <div className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h4 className="font-medium text-sm">What Suan-Pan remembers</h4>
          <button
            type="button"
            onClick={() => void refreshNotes()}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            refresh
          </button>
        </div>

        {notesLoading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {!notesLoading && notesError && (
          <p className="text-sm text-red-600">{notesError}</p>
        )}
        {!notesLoading && !notesError && notes.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Suan-Pan picks up your preferences as you chat. They'll appear
            here so you can review and remove any that are wrong.
          </p>
        )}

        {!notesLoading && !notesError && preferences.length > 0 && (
          <section>
            <h5 className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
              Preferences
            </h5>
            <ul className="divide-y border rounded">
              {preferences.map((n) => {
                const isPending = pendingForgetNote.has(n.id)
                return (
                  <li
                    key={n.id}
                    className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{n.content}</div>
                      <div className="text-xs text-muted-foreground">
                        {relativeTime(n.created_at)}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleForgetNote(n.id)}
                      disabled={isPending}
                      className="text-xs px-2 py-1 rounded border hover:bg-muted disabled:opacity-50"
                    >
                      {isPending ? 'forgetting…' : 'forget'}
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        {!notesLoading && !notesError && facts.length > 0 && (
          <section>
            <h5 className="text-xs uppercase tracking-wide text-muted-foreground mb-1">
              Facts
            </h5>
            <ul className="divide-y border rounded">
              {facts.map((n) => {
                const isPending = pendingForgetNote.has(n.id)
                return (
                  <li
                    key={n.id}
                    className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{n.content}</div>
                      <div className="text-xs text-muted-foreground">
                        {relativeTime(n.created_at)}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleForgetNote(n.id)}
                      disabled={isPending}
                      className="text-xs px-2 py-1 rounded border hover:bg-muted disabled:opacity-50"
                    >
                      {isPending ? 'forgetting…' : 'forget'}
                    </button>
                  </li>
                )
              })}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
