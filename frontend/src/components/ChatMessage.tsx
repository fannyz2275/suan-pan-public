import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import FindingCard from '@/components/FindingCard'
import type { FindingKind } from '@/lib/findingsClient'

interface Props {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  onFindingDecision?: (verdict: 'accept' | 'reject', label: string) => void
}

const FINDING_TAG = /<finding\s+id="([^"]+)"\s+kind="(recurring|transfer)"\s*>([\s\S]*?)<\/finding>/g

interface Segment {
  type: 'text' | 'finding'
  text?: string
  id?: string
  kind?: FindingKind
  body?: string
}

function splitFindingTags(content: string): Segment[] {
  const out: Segment[] = []
  let lastIdx = 0
  for (const m of content.matchAll(FINDING_TAG)) {
    if ((m.index ?? 0) > lastIdx) {
      out.push({ type: 'text', text: content.slice(lastIdx, m.index) })
    }
    out.push({
      type: 'finding',
      id: m[1],
      kind: m[2] as FindingKind,
      body: m[3].trim(),
    })
    lastIdx = (m.index ?? 0) + m[0].length
  }
  if (lastIdx < content.length) {
    out.push({ type: 'text', text: content.slice(lastIdx) })
  }
  return out
}

export default function ChatMessage({ role, content, streaming = false, onFindingDecision }: Props) {
  const isUser = role === 'user'
  const segments = isUser ? null : splitFindingTags(content)
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-2`}>
      <div
        className={`max-w-[85%] rounded-lg px-2.5 py-1.5 text-xs leading-relaxed ${
          isUser
            ? 'bg-primary text-primary-foreground whitespace-pre-wrap'
            : 'bg-muted text-foreground'
        }`}
      >
        {isUser ? (
          <>{content}</>
        ) : (
          segments!.map((seg, i) =>
            seg.type === 'text' ? (
              <div key={i} className="prose prose-xs max-w-none dark:prose-invert [&_table]:w-full [&_table]:text-xs [&_th]:text-left [&_th]:py-0.5 [&_td]:py-0.5 [&_table]:border-collapse [&_th]:border-b [&_td]:border-b [&_th]:border-muted-foreground/30 [&_td]:border-muted-foreground/20">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {seg.text ?? ''}
                </ReactMarkdown>
              </div>
            ) : (
              <FindingCard
                key={`${seg.id}-${i}`}
                id={seg.id!}
                kind={seg.kind!}
                body={seg.body!}
                onDecided={(verdict, label) => onFindingDecision?.(verdict, label)}
              />
            ),
          )
        )}
        {streaming && (
          <span
            aria-label="generating"
            className="inline-block w-1.5 h-3 ml-0.5 align-[-1px] bg-current animate-pulse"
          />
        )}
      </div>
    </div>
  )
}
