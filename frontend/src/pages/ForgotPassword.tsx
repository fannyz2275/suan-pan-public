import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${window.location.origin}/reset-password`,
      })
      if (error) throw error
      setSent(true)
    } catch {
      setError('Could not send a reset link. Please wait a moment and try again.')
    } finally { setBusy(false) }
  }
  return <div className="min-h-screen flex items-center justify-center bg-background p-4">
    <Card className="w-full max-w-sm">
      <CardHeader><CardTitle className="text-2xl">Forgot password?</CardTitle><CardDescription>Reset access to your existing account.</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        {sent ? <p role="status" className="text-sm">If an account exists for that email, a reset link has been requested. Check your inbox and spam folder.</p> :
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-1"><Label htmlFor="reset-email">Email</Label><Input id="reset-email" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} disabled={busy} /></div>
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <Button className="w-full" disabled={busy} type="submit">{busy ? 'Sending...' : 'Send reset link'}</Button>
          </form>}
        <Link to="/login" className="block text-sm underline">Back to sign in</Link>
      </CardContent>
    </Card>
  </div>
}
