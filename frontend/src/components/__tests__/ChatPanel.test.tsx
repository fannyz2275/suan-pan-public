import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import ChatPanel from '../ChatPanel'

// Minimal mock of supabase
vi.mock('@/lib/supabase', () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: { access_token: 'fake-token' } } }) } },
}))

function mockFetchSSE(chunks: (string | Uint8Array)[]) {
  // @ts-expect-error override
  global.fetch = vi.fn(async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        for (const c of chunks) controller.enqueue(typeof c === 'string' ? encoder.encode(c) : c)
        controller.close()
      },
    })
    return { ok: true, body: stream, status: 200 }
  })
}

describe('ChatPanel fragmented SSE', () => {
  it.each([
    ['split JSON and data prefix', ['da', 'ta: {"te', 'xt":"Buffered answer"}\n', '\ndata: {"session_id":"fragment-session","done":true}']],
    ['split CRLF framing', ['data: {"text":"Buffered answer"}\r', '\n\r', '\ndata: {"session_id":"fragment-session","done":true}\r', '\n']],
    ['final text without a newline', ['data: {"session_id":"fragment-session","done":true}\n\ndata: {"text":"Buffered ', 'answer"}']],
  ])('renders %s and preserves the session on follow-up', async (_name, chunks) => {
    mockFetchSSE(chunks)
    const user = userEvent.setup()
    render(<ChatPanel />)
    await user.type(screen.getByPlaceholderText(/ask/i), 'First question{Enter}')
    expect(await screen.findByText('Buffered answer')).toBeInTheDocument()
    await user.type(screen.getByPlaceholderText(/ask/i), 'Follow up{Enter}')
    const body = JSON.parse(vi.mocked(window.fetch).mock.calls[1][1]!.body as string)
    expect(body).toEqual({ message: 'Follow up', session_id: 'fragment-session' })
  })

  it('preserves multibyte UTF-8 characters when every byte arrives separately', async () => {
    const bytes = new TextEncoder().encode('data: {"text":"Saved \u00a5 and \u7b97"}\n\n')
    mockFetchSSE(Array.from(bytes, byte => Uint8Array.of(byte)))
    const user = userEvent.setup()
    render(<ChatPanel />)
    await user.type(screen.getByPlaceholderText(/ask/i), 'First question{Enter}')
    expect(await screen.findByText('Saved \u00a5 and \u7b97')).toBeInTheDocument()
  })
})

it('attaches metric context without overwriting a draft or auto-sending', async () => {
  mockFetchSSE(['data: {"text":"Explanation"}\n\n'])
  const user = userEvent.setup()
  const clear = vi.fn()
  const { rerender } = render(<ChatPanel />)
  await user.type(screen.getByPlaceholderText(/ask/i), 'What changed?')
  rerender(<ChatPanel context={{ label: 'Spending', prompt: 'Explain spending for 2020-02: 120.' }} onClearContext={clear} />)
  expect(window.fetch).not.toHaveBeenCalled()
  expect(screen.getByPlaceholderText(/ask/i)).toHaveValue('What changed?')
  await user.click(screen.getByRole('button', { name: 'Send' }))
  expect(await screen.findByText('Explanation')).toBeInTheDocument()
  const body = JSON.parse(vi.mocked(window.fetch).mock.calls[0][1]!.body as string)
  expect(body.message).toContain('Explain spending for 2020-02: 120.')
  expect(body.message).toContain('What changed?')
  expect(clear).toHaveBeenCalled()
})

describe('ChatPanel bulk recategorize confirm card', () => {
  beforeEach(() => { vi.resetAllMocks() })
  afterEach(() => { vi.useRealTimers() })

  it('renders confirm card when tool preview is streamed', async () => {
    const preview = JSON.stringify({
      tool_result: { tool: "bulk_recategorize", mode: "preview",
        new_category: "Shopping",
        matched: [{ id: "t1", date: "2025-12-03", description: "Amazon", amount: -42.18, old_category: "Other" }],
        updated_count: 0, failed_ids: [] }
    })
    mockFetchSSE([`data: ${preview}\n\n`, `data: ${JSON.stringify({ done: true, session_id: "s1" })}\n\n`])
    const user = userEvent.setup()
    render(<ChatPanel />)
    await user.type(screen.getByPlaceholderText(/ask/i), 'Reclassify Amazon')
    await user.keyboard('{Enter}')
    expect(await screen.findByText(/apply category 'shopping' to 1 txns/i)).toBeInTheDocument()
  })

  it('renders Retry button after an error and resends on click', async () => {
    const user = userEvent.setup()
    // First fetch returns HTTP 500
    let call = 0
    // @ts-expect-error override
    global.fetch = vi.fn(async () => {
      call++
      if (call === 1) return { ok: false, status: 500, text: async () => 'server error', body: null }
      // Second fetch — empty SSE but successful
      const stream = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('data: {"text":"hi"}\n\n')); c.close() } })
      return { ok: true, status: 200, body: stream }
    })
    render(<ChatPanel />)
    await user.type(screen.getByPlaceholderText(/ask/i), 'hello')
    await user.keyboard('{Enter}')
    const retry = await screen.findByRole('button', { name: /retry/i })
    await user.click(retry)
    expect(await screen.findByText(/hi/)).toBeInTheDocument()
  })

  it('cancels an in-flight stream when Cancel is clicked', async () => {
    const user = userEvent.setup()
    let abortSignal: AbortSignal | null = null

    // @ts-expect-error override
    global.fetch = vi.fn(async (_url, init: RequestInit) => {
      abortSignal = init.signal as AbortSignal
      // Never resolve until aborted
      return new Promise((_, reject) => {
        abortSignal!.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })
    })

    render(<ChatPanel />)
    await user.type(screen.getByPlaceholderText(/ask/i), 'slow')
    await user.keyboard('{Enter}')
    await user.click(await screen.findByRole('button', { name: /cancel/i }))
    expect(await screen.findByText(/cancelled by user/i)).toBeInTheDocument()
  })

  it('shows Retry button after cancel', async () => {
    const user = userEvent.setup()
    let abortSignal: AbortSignal | null = null
    // @ts-expect-error override
    global.fetch = vi.fn(async (_url, init: RequestInit) => {
      abortSignal = init.signal as AbortSignal
      return new Promise((_, reject) => {
        abortSignal!.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })
    })
    render(<ChatPanel />)
    await user.type(screen.getByPlaceholderText(/ask/i), 'hello')
    await user.keyboard('{Enter}')
    await user.click(await screen.findByRole('button', { name: /cancel/i }))
    expect(await screen.findByRole('button', { name: /retry/i })).toBeInTheDocument()
  })

  it('shows "Still thinking..." after 30s with no events', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    // @ts-expect-error override
    global.fetch = vi.fn(async () => new Promise(() => {}))  // never resolves
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) })
    render(<ChatPanel />)
    await user.type(screen.getByPlaceholderText(/ask/i), 'x')
    await user.keyboard('{Enter}')
    await act(async () => { vi.advanceTimersByTime(31000) })
    expect(await screen.findByText(/still thinking/i)).toBeInTheDocument()
    await act(async () => { vi.advanceTimersByTime(60000) })
    expect(await screen.findByText(/taking longer than expected/i)).toBeInTheDocument()
    vi.useRealTimers()
  })
})
