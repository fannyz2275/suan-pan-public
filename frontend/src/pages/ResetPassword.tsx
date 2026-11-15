import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export default function ResetPassword() {
  const [state, setState] = useState<'checking' | 'ready' | 'invalid' | 'done'>('checking')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const hash = new URLSearchParams(window.location.hash.slice(1))
    const query = new URLSearchParams(window.location.search)
    const linkError = hash.has('error') || hash.has('error_code') || query.has('error') || query.has('error_code')
    // getSession waits for the SDK to process the recovery URL automatically.
    supabase.auth.getSession().then(({ data, error }) => {
      if (active) setState(!linkError && !error && data.session ? 'ready' : 'invalid')
    }).catch(() => { if (active) setState('invalid') })
    return () => { active = false }
  }, [])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || state !== 'ready') return
    setError('')
    if (password !== confirmation) { setError('Passwords do not match.'); return }
    if (password.length < 8) { setError('Use at least 8 characters.'); return }
    setBusy(true)
    try {
      const { error } = await supabase.auth.updateUser({ password })
      if (error) { setError(error.message); return }
      setPassword('')
      setConfirmation('')
      setState('done')
      // Do not report a saved password as failed if local sign-out fails.
      try { await supabase.auth.signOut({ scope: 'local' }) } catch { /* Password is already saved. */ }
    } catch { setError('Could not update your password. Please try again.') }
    finally { setBusy(false) }
  }
  return <div className="min-h-screen flex items-center justify-center bg-background p-4">
    <Card className="w-full max-w-sm">
      <CardHeader><CardTitle className="text-2xl">Reset password</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {state === 'checking' && <p role="status" className="text-sm">Checking reset link...</p>}
        {state === 'invalid' && <><p role="alert" className="text-sm">This reset link is invalid or has expired. Request a new link to continue.</p><Link to="/forgot-password" className="block text-sm underline">Request a new reset link</Link></>}
        {state === 'done' && <p role="status" className="text-sm">Your password has been updated. You can now sign in with your new password.</p>}
        {state === 'ready' && <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1"><Label htmlFor="new-password">New password</Label><Input id="new-password" type="password" autoComplete="new-password" required minLength={8} value={password} onChange={e => setPassword(e.target.value)} disabled={busy} /><p className="text-xs text-muted-foreground">At least 8 characters.</p></div>
          <div className="space-y-1"><Label htmlFor="confirm-password">Confirm password</Label><Input id="confirm-password" type="password" autoComplete="new-password" required minLength={8} value={confirmation} onChange={e => setConfirmation(e.target.value)} disabled={busy} /></div>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy}>{busy ? 'Updating...' : 'Update password'}</Button>
          <Link to="/forgot-password" className="block text-sm underline">Request a new reset link</Link>
        </form>}
        <Link to="/login" className="block text-sm underline">Back to sign in</Link>
      </CardContent>
    </Card>
  </div>
}
