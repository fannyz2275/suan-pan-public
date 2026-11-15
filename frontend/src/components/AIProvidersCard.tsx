import { useEffect, useState } from 'react'
import api from '@/lib/api'
import { Button } from './ui/button'

type Provider = { provider: 'gemini' | 'openrouter'; configured: boolean; enabled: boolean; last_four?: string; updated_at?: string; validation_status?: string }
type State = { available: boolean; error?: string; providers: Provider[] }
const names = { gemini: 'Gemini', openrouter: 'OpenRouter' }

export default function AIProvidersCard() {
  const [data,setData]=useState<State|null>(null)
  const [error,setError]=useState(false)
  const [attempt,setAttempt]=useState(0)
  useEffect(()=>{
    let active=true
    api.get<State>('/profile/ai-providers').then(r=>{if(active){setData(r.data);setError(false)}}).catch(()=>{if(active)setError(true)})
    return ()=>{active=false}
  },[attempt])
  return <section aria-label="AI providers" className="rounded-lg border p-4 space-y-4">
    <h3 className="font-semibold">AI providers</h3>
    <p className="text-sm text-muted-foreground">Use your own API keys. Keys are encrypted on the server and cannot be viewed after saving. Advisor chat automatically uses OpenRouter when its key is saved; otherwise it uses Gemini. Provider usage is billed to your provider account.</p>
    {error && <p role="alert">Could not load provider settings. <button className="underline" onClick={()=>setAttempt(n=>n+1)}>Retry</button></p>}
    {!data && !error && <p role="status">Loading AI providers...</p>}
    {data && !data.available && <p role="alert">AI key storage is unavailable. Ask the operator to configure encryption and apply the provider-keys database migration.</p>}
    {data?.providers.map(p=><ProviderCard key={p.provider} provider={p} available={data.available} refresh={()=>setAttempt(n=>n+1)} />)}
  </section>
}
function ProviderCard({provider:p,available,refresh}:{provider:Provider;available:boolean;refresh:()=>void}) {
  const [key,setKey]=useState('')
  const [busy,setBusy]=useState(false)
  const [message,setMessage]=useState('')
  const [error,setError]=useState(false)
  const [confirmRemove,setConfirmRemove]=useState(false)
  const name=names[p.provider], path='/profile/ai-providers/'+p.provider
  async function act(action:'save'|'test'|'remove') {
    setBusy(true);setMessage('');setError(false)
    try {
      if(action==='save') { await api.put(path,{api_key:key});setKey('');setMessage('Key saved. Test it to check authentication.') }
      if(action==='test') { const {data}=await api.post(path+'/test');setMessage(data.valid ? 'Authentication succeeded. Model access and quota may differ.' : 'Authentication check failed. Check your key, provider access, and connection.');setError(!data.valid) }
      if(action==='remove') { await api.delete(path);setKey('');setConfirmRemove(false);setMessage('Key removed. Future AI requests require a new key.') }
      refresh()
    } catch { setError(true);setMessage('Could not complete this action. Check your connection and provider storage setup, then retry.') }
    finally {setBusy(false)}
  }
  return <div role="group" aria-label={name} className="border-t pt-4 space-y-3">
    <h4 className="font-medium">{name}</h4>
    <p className="text-xs text-muted-foreground">{p.provider==='gemini' ? 'Chat, statement imports, recurring assistance, and memory.' : 'Advisor chat takes priority when this key is saved. Statement imports and background features still require Gemini.'}</p>
    {!p.enabled && <p className="text-sm">Additional financial-analysis mode is not enabled in this deployment. Advisor chat can still use this key.</p>}
    <p className="text-sm">{p.configured ? `Saved key ending in ${p.last_four} · ${p.validation_status ?? 'untested'}` : 'No key saved'}</p>
    {p.updated_at && <p className="text-xs text-muted-foreground">Saved {new Date(p.updated_at).toLocaleString()}</p>}
    <label className="block text-sm">{name} API key<input aria-label={`${name} API key`} type="password" autoComplete="off" spellCheck={false} maxLength={4096} value={key} disabled={!available||busy} onChange={e=>setKey(e.target.value)} className="mt-1 block w-full min-w-0 rounded border px-3 py-2" /></label>
    <div className="flex flex-wrap gap-2">
      <Button disabled={!available||busy||key.length<8} onClick={()=>void act('save')}>{p.configured?'Replace':'Save'} {name} key</Button>
      <Button variant="outline" disabled={!available||busy||!p.configured} onClick={()=>void act('test')}>Test {name} key</Button>
      <Button variant="ghost" disabled={!available||busy||!p.configured} onClick={()=>setConfirmRemove(true)}>Remove {name} key</Button>
    </div>
    {confirmRemove && <div className="text-sm space-y-2"><p>Remove the saved {name} key? Requests already running may finish. This does not revoke the key at the provider.</p><Button disabled={busy} variant="destructive" onClick={()=>void act('remove')}>Confirm remove {name} key</Button> <Button disabled={busy} variant="ghost" onClick={()=>setConfirmRemove(false)}>Cancel</Button></div>}
    {busy && <p role="status">Updating {name}...</p>}
    {message && <p role={error?'alert':'status'} className="text-sm">{message}</p>}
  </div>
}
