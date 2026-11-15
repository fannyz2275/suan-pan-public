import { useCallback, useEffect, useState } from 'react'
import { usePlaidLink } from 'react-plaid-link'
import type { PlaidLinkOnSuccess } from 'react-plaid-link'
import { Button } from '@/components/ui/button'
import api from '@/lib/api'

interface Props {
  onConnected: () => void
}

export default function PlaidConnectButton({ onConnected }: Props) {
  const [attempt, setAttempt] = useState(0)
  return <PlaidConnection key={attempt} onConnected={onConnected} onRetry={() => setAttempt(n => n + 1)} />
}

function PlaidConnection({ onConnected, onRetry }: Props & { onRetry: () => void }) {
  const [linkToken, setLinkToken] = useState<string | null>(null)
  const [environment, setEnvironment] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    api.post<{ link_token: string; environment: string }>('/plaid/link-token', undefined, { signal: controller.signal, timeout: 15000 })
      .then((r) => {
        if (!controller.signal.aborted) {
          setLinkToken(r.data.link_token)
          setEnvironment(r.data.environment)
        }
      })
      .catch(() => { if (!controller.signal.aborted) setError('Could not initialize the bank connection. Check your connection or the server Plaid configuration.') })
    return () => controller.abort()
  }, [])

  const onSuccess = useCallback<PlaidLinkOnSuccess>(async (publicToken, metadata) => {
    setSyncing(true)
    setError(null)
    try {
      await api.post('/plaid/exchange', {
        public_token: publicToken,
        institution_name: metadata.institution?.name ?? 'Bank',
      })
      onConnected()
    } catch {
      setError('Failed to sync accounts — try again')
    } finally {
      setSyncing(false)
    }
  }, [onConnected])

  const onExit = useCallback((exitError: unknown) => {
    if (exitError) setError('The bank connection closed with an error. Retry to start a new session.')
  }, [])
  const { open, ready, error: plaidError } = usePlaidLink({ token: linkToken, onSuccess, onExit })

  useEffect(() => {
    if (ready || error || plaidError) return
    const timer = setTimeout(() => setError('The bank connection is taking too long to load. Check your connection and retry. If it persists, try an external browser.'), 20000)
    return () => clearTimeout(timer)
  }, [ready, error, plaidError])

  const message = error || (plaidError ? 'Plaid could not load. Check browser content blockers or try an external browser.' : null)
  if (message) {
    return <div className="space-y-2 max-w-sm"><p role="alert" className="text-xs text-destructive">{message}</p><Button size="sm" variant="outline" onClick={onRetry}>Retry bank connection</Button></div>
  }

  return (
    <Button
      size="sm"
      variant="outline"
      onClick={() => {
        if (environment === 'sandbox' && !ready) {
          window.alert('Plaid Sandbox mode\n\nThis is a test environment, not a live bank connection. Do not enter real banking credentials.\n\nPlaid is still loading. Please try again shortly; a retry option will appear if loading times out.')
          return
        }
        if (environment === 'sandbox' && !window.confirm('Plaid Sandbox mode\n\nThis is a test connection using simulated banks and financial data, not a live bank connection. Do not enter real banking credentials. Test accounts may be added to your dashboard.\n\nSelect OK to continue with a test connection, or Cancel to go back.')) return
        open()
      }}
      disabled={(!ready && environment !== 'sandbox') || syncing}
    >
      {syncing ? 'Syncing…' : !ready && environment !== 'sandbox' ? 'Loading bank connection…' : 'Connect Bank'}
    </Button>
  )
}
