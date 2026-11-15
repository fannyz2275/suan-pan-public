import { useEffect, useRef, useState } from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import ChatMessage from './ChatMessage'
import TablePill, { type DisplayableTable } from './TablePill'
import AttributionChips from './portfolio/AttributionChips'
import BulkRecategorizeConfirmCard, { type BulkPreview } from './BulkRecategorizeConfirmCard'
import { FeedbackBar, type FeedbackLabels } from './FeedbackBar'
import { submitFeedback } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import type { AttributionResult } from '@/lib/portfolio'
import type { AdvisorContext } from '@/lib/advisorContext'
import PendingAnalysis, { type PendingAnalysisState } from './PendingAnalysis'
import { X } from 'lucide-react'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

interface Message {
  role: 'user' | 'assistant'
  content: string
  isError?: boolean
  id?: string
}

const emptyLabels = (): FeedbackLabels => ({
  accurate_numbers: false,
  inaccurate_numbers: false,
  on_topic: false,
  off_topic: false,
  good_advice: false,
  bad_advice: false,
})

interface Props {
  context?: AdvisorContext | null
  onClearContext?: () => void
  active?: boolean
  className?: string
  // Called after any advisor turn that could have mutated server-side data
  // (tool calls like rescan_transfers / bulk_recategorize, or goal/action-item
  // extraction at stream end). The parent uses this to re-fetch the widgets
  // whose data the chat turn may have changed.
  onChanged?: () => void
  onRequestUpload?: () => void
  importRevision?: number
}

// Tool calls that mutate data on the server. When the stream reports one
// running, the parent should refresh once the turn ends.
const MUTATING_TOOLS = new Set([
  'update_transaction_category',
  'bulk_recategorize',
  'rescan_transfers',
])

// Mirror of backend strip_actions_block (advisor/parser.py). The persistence
// path strips this server-side; the streamed body does not — so we strip on
// the client to avoid leaking the JSON action block into the visible chat.
//
// Only strip when <actions> is followed by JSON-shaped content (whitespace
// then `{`). Otherwise the model is referring to the tag literally in prose
// (e.g. "details in an `<actions>` block") and we must leave it alone — the
// previous regex stripped everything to end-of-string in that case, which
// truncated long replies on a markdown-token boundary (gap-registry G-020).
const ACTIONS_STRIP_CLOSED_RE = /\s*<actions>\s*\{[\s\S]*?<\/actions>/g
const ACTIONS_STRIP_OPEN_RE = /\s*<actions>\s*\{[\s\S]*$/

function stripActionsBlock(text: string): string {
  return text
    .replace(ACTIONS_STRIP_CLOSED_RE, '')
    .replace(ACTIONS_STRIP_OPEN_RE, '')
    .trimEnd()
}

export default function ChatPanel({ className = '', onChanged, context, onClearContext, active = true, onRequestUpload, importRevision = 0 }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [toolStatus, setToolStatus] = useState<string | null>(null)
  const [pendingPreview, setPendingPreview] = useState<BulkPreview | null>(null)
  const [lastUserMessage, setLastUserMessage] = useState<string>('')
  const [stallLevel, setStallLevel] = useState<0 | 1 | 2>(0)
  const [feedbackByMessageId, setFeedbackByMessageId] = useState<Record<string, FeedbackLabels>>({})
  const [tablesByMessageId, setTablesByMessageId] = useState<Record<string, DisplayableTable[]>>({})
  const pendingTablesRef = useRef<DisplayableTable[]>([])
  const [attributionByMessageId, setAttributionByMessageId] = useState<Record<string, AttributionResult>>({})
  const pendingAttributionRef = useRef<AttributionResult | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const lastEventRef = useRef<number>(Date.now())
  const bottomRef = useRef<HTMLDivElement>(null)
  const [analysisEnabled, setAnalysisEnabled] = useState(false)
  const [analysisMode, setAnalysisMode] = useState(true)
  const [pendingAnalysis, setPendingAnalysis] = useState<PendingAnalysisState | null>(null)
  const ownerRef = useRef<string | null>(null)
  const resumeBusy = useRef(false)
  const sendStarted = useRef(false)

  useEffect(() => {
    let disposed = false
    void (async () => {
      const { data } = await supabase.auth.getSession()
      const uid = data.session?.user?.id
      if (!uid || disposed) return
      ownerRef.current = uid
      const headers = { Authorization: `Bearer ${data.session!.access_token}` }
      try {
        const config = await fetch(`${BASE_URL}/advisor/analysis/config`, { headers }).then(r => r.ok ? r.json() : { enabled: false })
        if (disposed) return
        setAnalysisEnabled(Boolean(config.enabled))
        const saved = localStorage.getItem(`advisor-session:${uid}`)
        if (saved === 'new' || sendStarted.current) return
        const sessions = saved ? [{ id: saved }] : await fetch(`${BASE_URL}/advisor/sessions`, { headers }).then(r => r.ok ? r.json() : [])
        if (!sessions[0]?.id) return
        const response = await fetch(`${BASE_URL}/advisor/sessions/${sessions[0].id}/messages`, { headers })
        if (!response.ok) return
        const restored = await response.json()
        if (disposed || sendStarted.current) return
        setSessionId(sessions[0].id)
        setMessages(restored.map((m: Message) => ({ id: m.id, role: m.role, content: m.content })))
      } catch { /* Existing chat remains usable when restoration is unavailable. */ }
    })()
    return () => { disposed = true }
  }, [])

  useEffect(() => {
    if (ownerRef.current) localStorage.setItem(`advisor-session:${ownerRef.current}`, sessionId ?? 'new')
    if (!analysisEnabled || !sessionId) return
    let disposed = false
    void (async () => {
      try {
        const { data } = await supabase.auth.getSession()
        const response = await fetch(`${BASE_URL}/advisor/sessions/${sessionId}/pending-analysis`, {
          headers: { Authorization: `Bearer ${data.session?.access_token ?? ''}` },
        })
        if (response.ok) {
          const payload = await response.json()
          if (!disposed) setPendingAnalysis(payload.pending)
        }
      } catch { /* Do not replace a known pending question with a network error. */ }
    })()
    return () => { disposed = true }
  }, [sessionId, analysisEnabled, importRevision])

  const continueAnalysis = async () => {
    if (!pendingAnalysis || resumeBusy.current || streaming) return
    resumeBusy.current = true
    setStreaming(true)
    try {
      const { data } = await supabase.auth.getSession()
      const response = await fetch(`${BASE_URL}/advisor/pending-analysis/${pendingAnalysis.id}/resume`, {
        method: 'POST', headers: { Authorization: `Bearer ${data.session?.access_token ?? ''}` },
      })
      if (!response.ok) throw new Error('Continuation could not finish. Your question is saved; check the required data before retrying.')
      const result = await response.json()
      setMessages(prev => [...prev, { role: 'assistant', content: result.answer, id: result.message_id }])
      setPendingAnalysis(null)
      onChanged?.()
    } catch (error) {
      setMessages(prev => [...prev, { role: 'assistant', content: error instanceof Error ? error.message : 'Continuation failed.', isError: true }])
    } finally { resumeBusy.current = false; setStreaming(false) }
  }

  useEffect(() => {
    if (active) bottomRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' })
  }, [messages, toolStatus, pendingPreview, active])

  useEffect(() => {
    const onStarted = (e: Event) => {
      const ce = e as CustomEvent<string>
      if (!ce.detail) return
      setSessionId(ce.detail)
      setMessages([])
      void send('Begin findings review.', ce.detail)
    }
    window.addEventListener('findings-review-started', onStarted)
    return () => window.removeEventListener('findings-review-started', onStarted)
    // `send` reads `streaming` and other state; effect runs once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!streaming) {
      setStallLevel(0)
      return
    }
    const id = setInterval(() => {
      const idle = Date.now() - lastEventRef.current
      if (idle > 90000) setStallLevel(2)
      else if (idle > 30000) setStallLevel(1)
      else setStallLevel(0)
    }, 1000)
    return () => clearInterval(id)
  }, [streaming])

  const send = async (override?: string, reviewSessionId?: string) => {
    const text = override ?? (context ? `${context.prompt}${input.trim() ? `\n\nMy question: ${input.trim()}` : ''}` : input.trim())
    if (!text || streaming) return
    sendStarted.current = true
    // Flip streaming synchronously within the same event-loop tick so
    // reentry from a double-click (or concurrent Enter + click) is blocked
    // before the first await yields control.
    setStreaming(true)
    setStallLevel(0)
    lastEventRef.current = Date.now()
    if (!override) {
      setInput('')
      onClearContext?.()
    }
    setLastUserMessage(text)
    setMessages((prev) => [...prev, { role: 'user', content: text }])

    const { data } = await supabase.auth.getSession()
    const token = data.session?.access_token ?? ''

    const controller = new AbortController()
    abortRef.current = controller

    // Track at send-scope so the finally block can decide whether the parent
    // should refetch. `mutated` flips on mutating tool calls; `assistantText`
    // growing past empty indicates the model produced output (which may have
    // parsed out structured goals / action items server-side).
    let assistantText = ''
    let mutated = false

    try {
      if (analysisEnabled && analysisMode && !reviewSessionId) {
        const response = await fetch(`${BASE_URL}/advisor/analysis`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ message: text, session_id: sessionId }), signal: controller.signal,
        })
        if (!response.ok) {
          setMessages(prev => [...prev, { role: 'assistant', content: 'Analysis could not finish. No unverified answer was shown. Please try again.', isError: true }])
          return
        }
        const result = await response.json()
        assistantText = result.answer
        setSessionId(result.session_id)
        setMessages(prev => [...prev, { role: 'assistant', content: result.answer, id: result.message_id }])
        if (result.pending) setPendingAnalysis({ ...result.pending, ready: false, missing: result.pending.requirements,
          upload_action: result.pending.requirements.some((k: string) => ['aligned_wealth', 'complete_cost_basis'].includes(k)) ? 'upload_statements' : null })
        return
      }
      const res = await fetch(`${BASE_URL}/advisor/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message: text, session_id: reviewSessionId ?? sessionId }),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) {
        setMessages((prev) => [...prev, { role: 'assistant', content: 'Error: request failed. Please try again.', isError: true }])
        return
      }

      setMessages((prev) => [...prev, { role: 'assistant', content: '' }])

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let pendingLine = ''

      while (true) {
        const { done, value } = await reader.read()
        pendingLine += done ? decoder.decode() : decoder.decode(value, { stream: true })
        const lines = pendingLine.split('\n')
        // Reads can end inside an SSE line or a UTF-8 character. Only parse
        // complete lines until EOF, when the decoder and final line flush.
        pendingLine = done ? '' : lines.pop() ?? ''
        for (const line of lines) {
          // Reset stall timer on any non-empty SSE line (data, keepalive
          // comments, etc.). Skipping empty lines preserves stall detection
          // on an abruptly-ended stream that only emits blank framing.
          if (line.length > 0) {
            lastEventRef.current = Date.now()
            setStallLevel(0)
          }
          // Keepalive comment frames (": ...") count as liveness but carry
          // no payload to parse.
          if (line.startsWith(': ')) continue
          if (!line.startsWith('data: ')) continue
          try {
            const payload = JSON.parse(line.slice(6))
            if (payload.replace_text) {
              assistantText = ''
              setMessages((prev) => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: '' }
                return next
              })
              continue
            }
            if (payload.text) {
              assistantText += payload.text
              const display = stripActionsBlock(assistantText)
              setMessages((prev) => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: display }
                return next
              })
            }
            if ((payload.pii_redacted || payload.internal_redacted || payload.table_stripped) && typeof payload.redacted_text === 'string') {
              // Server-side post-stream pass replaced sensitive tokens that
              // already streamed into the visible chat. Overwrite the
              // assistant bubble so the rendered text matches what gets
              // persisted (and what the next turn's context replay sees).
              assistantText = payload.redacted_text
              const display = stripActionsBlock(assistantText)
              setMessages((prev) => {
                const next = [...prev]
                next[next.length - 1] = { role: 'assistant', content: display }
                return next
              })
            }
            if (payload.tool_call) {
              if (payload.status === 'running') {
                const labels: Record<string, string> = {
                  get_transactions: 'Looking up transactions',
                  get_spending_by_category: 'Analyzing spending',
                  detect_transfers: 'Detecting transfers',
                  update_transaction_category: 'Updating category',
                  compare_spending_periods: 'Comparing periods',
                  bulk_recategorize: 'Recategorizing transactions',
                  rescan_transfers: 'Rescanning transfers',
                }
                setToolStatus(labels[payload.tool_call as string] ?? 'Running tool')
                if (MUTATING_TOOLS.has(payload.tool_call as string)) {
                  mutated = true
                }
              } else {
                setToolStatus(null)
              }
            }
            if (payload.tool_result?.tool === 'bulk_recategorize' && payload.tool_result.mode === 'preview') {
              // If a preview card is already pending, keep the existing one
              // and drop the new preview silently (queueing is overkill for
              // now — a subsequent user turn will re-request if needed).
              // The card resolves to null on confirm or cancel, at which
              // point the next preview will be allowed through.
              setPendingPreview((prev) => {
                if (prev !== null) {
                  console.warn('Dropping incoming bulk_recategorize preview — a prior preview is still pending confirmation.')
                  return prev
                }
                return payload.tool_result as BulkPreview
              })
            }
            if (payload.displayable_table) {
              // Backend tagged a bulky tool result for inline-card rendering.
              // Buffer until the assistant message_id arrives at stream end,
              // then attach by id so the card sticks to the right turn.
              const { tool: _t, ...table } = payload.displayable_table as DisplayableTable & { tool?: string }
              pendingTablesRef.current = [...pendingTablesRef.current, table]
            }
            if (payload.attribution_result) {
              // Backend emitted an attribution payload for portfolio_get_attribution.
              // Buffer until the message_id arrives at stream end.
              pendingAttributionRef.current = payload.attribution_result as AttributionResult
            }
            if (payload.session_id) {
              setSessionId(payload.session_id)
            }
            if (payload.done && payload.message_id) {
              const messageId = payload.message_id as string
              setMessages((prev) => {
                const next = [...prev]
                for (let i = next.length - 1; i >= 0; i--) {
                  if (next[i].role === 'assistant') {
                    next[i] = { ...next[i], id: messageId }
                    break
                  }
                }
                return next
              })
              if (pendingTablesRef.current.length > 0) {
                const tables = pendingTablesRef.current
                setTablesByMessageId((prev) => ({ ...prev, [messageId]: tables }))
                pendingTablesRef.current = []
              }
              if (pendingAttributionRef.current !== null) {
                const attribution = pendingAttributionRef.current
                setAttributionByMessageId((prev) => ({ ...prev, [messageId]: attribution }))
                pendingAttributionRef.current = null
              }
            }
          } catch {
            // ignore parse errors
          }
        }
        if (done) break
      }
    } catch (e) {
      if ((e as { name?: string })?.name === 'AbortError') {
        setPendingPreview(null)
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.role === 'assistant') {
            next[next.length - 1] = { ...last, content: (last.content || '') + '\n\n[Cancelled by user]', isError: true }
          } else {
            next.push({ role: 'assistant', content: '[Cancelled by user]', isError: true })
          }
          return next
        })
        return
      }
      throw e
    } finally {
      abortRef.current = null
      setToolStatus(null)
      setStreaming(false)
      // The backend may have also created goals/action items by parsing the
      // response text, so refresh on every turn — not just on tool mutations.
      if (mutated || assistantText) onChanged?.()
    }
  }

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  const hasConversation = sessionId !== null || messages.length > 0

  const resetConversation = () => {
    if (streaming) return
    setSessionId(null)
    sendStarted.current = true
    setPendingAnalysis(null)
    setMessages([])
    setToolStatus(null)
    setInput('')
    onClearContext?.()
    // A leftover bulk-recategorize confirm card from the previous session is
    // ambiguous (it would apply against the new conversation's history) and
    // visually broken if its tool result was an error — drop it on reset.
    setPendingPreview(null)
    setTablesByMessageId({})
    pendingTablesRef.current = []
    setAttributionByMessageId({})
    pendingAttributionRef.current = null
  }

  return (
    <div className={`flex flex-col min-h-0 ${className}`}>
      {/* Conversation status bar */}
      <div className="shrink-0 px-4 py-2 border-b bg-muted/30 flex items-center justify-between text-xs">
        <div className="flex items-center gap-2 text-muted-foreground">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              streaming
                ? 'bg-primary animate-pulse'
                : hasConversation
                  ? 'bg-emerald-500'
                  : 'bg-muted-foreground/40'
            }`}
          />
          {streaming
            ? 'Advisor is responding…'
            : hasConversation
              ? `In conversation · ${messages.length} message${messages.length === 1 ? '' : 's'}`
              : 'New conversation — ask anything to begin'}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={resetConversation}
          disabled={streaming || !hasConversation}
          title="End this conversation and start fresh"
        >
          End &amp; start new
        </Button>
      </div>

      {analysisEnabled && <div className="px-4 py-2 border-b">
        <label className="text-xs text-muted-foreground">Mode <select aria-label="Advisor mode" value={analysisMode ? 'analysis' : 'actions'} onChange={e => setAnalysisMode(e.target.value === 'analysis')} disabled={streaming} className="ml-2 bg-background border px-2 py-1 text-sm">
          <option value="analysis">Financial analysis</option><option value="actions">Goals and actions</option>
        </select></label>
      </div>}
      <PendingAnalysis pending={pendingAnalysis} busy={streaming} onContinue={() => void continueAnalysis()} onUpload={onRequestUpload} />

      {/* Messages area */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        {messages.length === 0 && (
          <p className="text-xs text-muted-foreground text-center mt-8">
            Ask me anything about your finances.
          </p>
        )}
        {(() => {
          const lastAssistantIndex = messages.map((m) => m.role).lastIndexOf('assistant')
          const reviewPromptIndex =
            lastAssistantIndex >= 0 &&
            messages[lastAssistantIndex].content.startsWith('I noticed a possible recurring')
              ? lastAssistantIndex
              : -1
          return messages.map((m, i) => {
            const isLastAssistant = m.role === 'assistant' && i === messages.length - 1
            return (
              <div key={m.id ?? `local-${i}`}>
                {m.role === 'assistant' && m.id && attributionByMessageId[m.id] && (
                  <AttributionChips data={attributionByMessageId[m.id]} />
                )}
                <ChatMessage
                  role={m.role}
                  content={m.content}
                  streaming={streaming && isLastAssistant && !!m.content}
                  onFindingDecision={(verdict, label) => {
                    const word = verdict === 'accept' ? 'Confirmed' : 'Rejected'
                    void send(`${word}: ${label}`)
                  }}
                />
                {m.role === 'assistant' && m.id && (tablesByMessageId[m.id] ?? []).map((t, ti) => (
                  <TablePill key={`${m.id}-tbl-${ti}`} table={t} />
                ))}
                {m.role === 'assistant' && m.id && (
                  <FeedbackBar
                    labels={feedbackByMessageId[m.id] ?? emptyLabels()}
                    onChange={(next) => {
                      const id = m.id!
                      setFeedbackByMessageId((prev) => ({ ...prev, [id]: next }))
                      return submitFeedback(id, next)
                    }}
                  />
                )}
                {i === reviewPromptIndex && !streaming && (
                  <div className="flex gap-2 justify-start mb-3 -mt-2 pl-1">
                    <Button size="sm" variant="outline" onClick={() => void send('yes')}>
                      Yes
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => void send('no')}>
                      No
                    </Button>
                  </div>
                )}
              </div>
            )
          })
        })()}
        {(() => {
          const last = messages[messages.length - 1]
          if (last?.role === 'assistant' && last.isError && !streaming) {
            return (
              <button
                type="button"
                className="ml-2 text-xs underline"
                onClick={() => void send(lastUserMessage)}
              >
                Retry
              </button>
            )
          }
          return null
        })()}
        {toolStatus && (
          <div className="flex justify-start mb-3">
            <div className="bg-muted text-muted-foreground text-xs rounded-lg px-3 py-2 flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-primary animate-pulse" />
              {toolStatus}…
            </div>
          </div>
        )}
        {streaming && stallLevel === 1 && (
          <div className="text-xs text-muted-foreground mt-1">Still thinking...</div>
        )}
        {streaming && stallLevel === 2 && (
          <div className="text-xs text-muted-foreground mt-1">
            This is taking longer than expected — you can cancel and try again.
          </div>
        )}
        {pendingPreview && (
          <BulkRecategorizeConfirmCard
            preview={pendingPreview}
            disabled={streaming}
            onConfirm={() => {
              setPendingPreview(null)
              void send('Confirmed: apply the recategorization.')
            }}
            onCancel={() => setPendingPreview(null)}
          />
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      {context && <div className="border-t px-3 py-2 text-xs flex items-start gap-2">
        <details className="min-w-0 flex-1"><summary className="cursor-pointer font-medium">Explain: {context.label}</summary><p className="mt-2 whitespace-pre-wrap break-words max-h-40 overflow-auto">{context.prompt}</p></details>
        <button aria-label="Remove metric context" title="Remove metric context" onClick={onClearContext} className="p-1 shrink-0"><X size={14} /></button>
      </div>}
      <div className="shrink-0 border-t p-2 flex gap-2">
        <Input
          placeholder="Ask your advisor…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={streaming}
          className="flex-1"
        />
        {streaming ? (
          <Button onClick={() => abortRef.current?.abort()} size="sm" variant="secondary">
            Cancel
          </Button>
        ) : (
          <Button onClick={() => send()} disabled={!input.trim() && !context} size="sm">
            Send
          </Button>
        )}
      </div>
    </div>
  )
}
