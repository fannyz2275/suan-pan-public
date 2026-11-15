import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ImportToastContext as Ctx, type ToastState } from '../contexts/ImportToastContext'

interface ProviderProps {
  children: ReactNode
}

export default function ImportToastProvider({ children }: ProviderProps) {
  const [toast, setToast] = useState<ToastState | null>(null)
  const timerRef = useRef<number | null>(null)

  const dismiss = useCallback(() => {
    setToast(null)
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const showImportToast = useCallback((state: ToastState) => {
    setToast(state)
    if (timerRef.current != null) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => setToast(null), 8000)
  }, [])

  useEffect(() => () => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current)
  }, [])

  return (
    <Ctx.Provider value={{ showImportToast }}>
      {children}
      {toast && (
        <div
          data-testid="import-toast"
          className="fixed top-4 right-4 z-[60] max-w-md rounded-lg border bg-background shadow-lg px-4 py-3 flex items-start gap-3"
        >
          <div className="flex-1 text-sm">
            <p>{toast.message}</p>
            {toast.transferCount > 0 && (
              <p className="mt-1">
                <span className="font-semibold">{toast.transferCount} new transfer candidate{toast.transferCount === 1 ? '' : 's'}</span>{' '}
                found —{' '}
                {toast.onReview ? (
                  <button
                    data-testid="import-toast-review"
                    className="underline text-primary"
                    onClick={() => { toast.onReview?.(); dismiss() }}
                  >
                    Review now
                  </button>
                ) : null}
              </p>
            )}
          </div>
          <button
            onClick={dismiss}
            aria-label="Dismiss"
            className="text-muted-foreground hover:text-foreground"
          >×</button>
        </div>
      )}
    </Ctx.Provider>
  )
}
