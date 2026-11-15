import { useRef, useState } from 'react'
import { ThumbsUp, ThumbsDown, X } from 'lucide-react'

export type FeedbackLabels = {
  helpful?: boolean;
  not_helpful?: boolean;
  too_technical?: boolean;
  accurate_numbers: boolean;
  inaccurate_numbers: boolean;
  on_topic: boolean;
  off_topic: boolean;
  good_advice: boolean;
  bad_advice: boolean;
};

const REASONS: { key: keyof FeedbackLabels; display: string }[] = [
  { key: 'inaccurate_numbers', display: 'The numbers look wrong' },
  { key: 'off_topic', display: 'It missed my question' },
  { key: 'bad_advice', display: "The advice doesn't fit my situation" },
  { key: 'too_technical', display: 'Too technical or confusing' },
]
const cleared = (): FeedbackLabels => ({ helpful: false, not_helpful: false, too_technical: false, accurate_numbers: false, inaccurate_numbers: false, on_topic: false, off_topic: false, good_advice: false, bad_advice: false })

export function FeedbackBar({
  labels,
  onChange,
}: {
  labels: FeedbackLabels;
  onChange: (next: FeedbackLabels) => void | Promise<unknown>;
}) {
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'removed' | 'error'>('idle')
  const pending = useRef<FeedbackLabels | null>(null)
  const busy = useRef(false)
  const positive = Boolean(labels.helpful || labels.good_advice || labels.accurate_numbers || labels.on_topic)
  const negative = Boolean(labels.not_helpful || labels.inaccurate_numbers || labels.off_topic || labels.bad_advice || labels.too_technical)
  const save = async (next: FeedbackLabels) => {
    if (busy.current) return
    busy.current = true
    pending.current = next
    setStatus('saving')
    try {
      await onChange(next)
      setStatus(Object.values(next).some(Boolean) ? 'saved' : 'removed')
    } catch { setStatus('error') }
    finally { busy.current = false }
  }
  return (
    <div className="mt-1 mb-3 space-y-2 text-xs">
      <div className="flex items-center gap-1" role="group" aria-label="Response feedback">
        <button type="button" aria-label="Helpful" title="Helpful" aria-pressed={positive && !negative} disabled={status === 'saving'} className="p-2 rounded hover:bg-muted aria-pressed:bg-emerald-100 aria-pressed:text-emerald-900" onClick={() => void save({ ...cleared(), helpful: !(positive && !negative) })}><ThumbsUp size={15} /></button>
        <button type="button" aria-label="Not helpful" title="Not helpful" aria-pressed={negative} disabled={status === 'saving'} className="p-2 rounded hover:bg-muted aria-pressed:bg-rose-100 aria-pressed:text-rose-900" onClick={() => void save({ ...cleared(), not_helpful: !negative })}><ThumbsDown size={15} /></button>
        {(positive || negative) && <button type="button" aria-label="Remove feedback" title="Remove feedback" disabled={status === 'saving'} className="p-2" onClick={() => void save(cleared())}><X size={14} /></button>}
        <span role="status" className="text-muted-foreground">{status === 'saving' ? 'Saving...' : status === 'saved' ? 'Feedback saved' : status === 'removed' ? 'Feedback removed' : ''}</span>
      </div>
      {negative && <fieldset className="space-y-2 border-l-2 pl-3"><legend className="text-muted-foreground mb-2">What could be better? (optional)</legend>{REASONS.map(({ key, display }) => <label key={key} className="flex items-start gap-2"><input type="checkbox" checked={Boolean(labels[key])} disabled={status === 'saving'} onChange={() => void save({ ...labels, helpful: false, not_helpful: true, [key]: !labels[key] })} />{display}</label>)}</fieldset>}
      {status === 'error' && <div role="alert">Could not save feedback. <button type="button" aria-label="Retry feedback" className="underline" onClick={() => pending.current && void save(pending.current)}>Retry</button></div>}
    </div>
  );
}
