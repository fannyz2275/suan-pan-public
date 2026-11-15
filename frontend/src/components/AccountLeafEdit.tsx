import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { accountsApi } from '@/lib/api'
import type { Account } from '@/lib/types'

const NUMERIC_FIELDS = new Set<keyof Account>([
  'balance', 'estimated_value', 'purchase_price', 'vested_shares',
  'unvested_shares', 'grant_price', 'ownership_pct', 'estimated_valuation',
  'liquidity_horizon_months',
])

export function EditFields({
  draft, onChange, idPrefix,
}: {
  draft: Account
  onChange: (field: keyof Account, value: string) => void
  idPrefix: string
}) {
  const num = (field: keyof Account, label: string) => {
    const fieldId = `${idPrefix}-${String(field)}`
    return (
      <div className="space-y-1" key={field}>
        <Label htmlFor={fieldId} className="text-xs">{label}</Label>
        <Input
          id={fieldId}
          type="number"
          value={(draft[field] as number | null | undefined) ?? ''}
          onChange={(e) => onChange(field, e.target.value)}
          className="h-7 text-sm"
        />
      </div>
    )
  }
  const text = (field: keyof Account, label: string) => {
    const fieldId = `${idPrefix}-${String(field)}`
    return (
      <div className="space-y-1" key={field}>
        <Label htmlFor={fieldId} className="text-xs">{label}</Label>
        <Input
          id={fieldId}
          value={(draft[field] as string | null | undefined) ?? ''}
          onChange={(e) => onChange(field, e.target.value)}
          className="h-7 text-sm"
        />
      </div>
    )
  }

  const base = (
    <>
      {text('name', 'Name')}
      {num('balance', 'Balance ($)')}
    </>
  )
  if (['checking', 'savings', 'brokerage', 'retirement', 'debt'].includes(draft.type)) return <>{base}</>
  if (draft.type === 'property') return <>{text('name', 'Name')}{num('estimated_value', 'Estimated Value ($)')}{num('purchase_price', 'Purchase Price ($)')}</>
  if (draft.type === 'rsu') return <>{text('name', 'Name')}{num('vested_shares', 'Vested Shares')}{num('unvested_shares', 'Unvested Shares')}{num('grant_price', 'Grant Price ($)')}</>
  if (draft.type === 'business') return <>{text('name', 'Name')}{num('estimated_valuation', 'Estimated value ($)')}{num('ownership_pct', 'Ownership %')}{num('liquidity_horizon_months', 'Months until you could cash out')}</>
  return <>{base}</>
}

export function NicknameAndLast4Fields({
  nickname, last4, onChange, idPrefix,
}: {
  nickname: string | null | undefined
  last4: string | null | undefined
  onChange: (patch: Partial<Account>) => void
  idPrefix: string
}) {
  const nicknameId = `${idPrefix}-nickname`
  const last4Id = `${idPrefix}-last4`
  return (
    <>
      <div className="space-y-1">
        <Label htmlFor={nicknameId} className="text-xs">Nickname (optional)</Label>
        <Input
          id={nicknameId}
          value={nickname ?? ''}
          onChange={(e) => onChange({ nickname: e.target.value || null })}
          className="h-7 text-sm"
          placeholder="e.g. Joint"
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={last4Id} className="text-xs">Last 4 digits (optional)</Label>
        <Input
          id={last4Id}
          inputMode="numeric"
          maxLength={4}
          pattern="\\d{4}"
          value={last4 ?? ''}
          onChange={(e) => {
            const v = e.target.value.replace(/\D/g, '').slice(0, 4)
            onChange({ account_number_last4: v || null })
          }}
          className="h-7 text-sm"
          placeholder="1234"
        />
      </div>
    </>
  )
}

interface Props {
  account: Account
  onChanged: () => void
  onCancel: () => void
}

export default function AccountLeafEdit({ account, onChanged, onCancel }: Props) {
  const [draft, setDraft] = useState<Account>(account)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { setDraft(account) }, [account])

  const handleChange = (field: keyof Account, value: string) => {
    setDraft((prev) => ({
      ...prev,
      [field]: NUMERIC_FIELDS.has(field) ? (value === '' ? null : Number(value)) : value,
    }))
  }
  const handlePatch = (patch: Partial<Account>) => {
    setDraft((prev) => ({ ...prev, ...patch }))
  }

  const save = async () => {
    setSaving(true); setError(null)
    try {
      const { id: _id, ...payload } = draft
      await accountsApi.update(account.id, payload)
      onChanged()
    } catch {
      setError('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    setDeleting(true); setError(null)
    try {
      await accountsApi.remove(account.id)
      onChanged()
    } catch {
      setError('Failed to delete. Please try again.')
      setDeleting(false)
    }
  }

  return (
    <div className="border-t px-3 py-3 bg-muted/20 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <NicknameAndLast4Fields
          nickname={draft.nickname}
          last4={draft.account_number_last4}
          onChange={handlePatch}
          idPrefix={`leaf-${account.id}`}
        />
        <EditFields draft={draft} onChange={handleChange} idPrefix={`leaf-${account.id}`} />
      </div>
      {confirmingDelete ? (
        <div className="flex gap-2 pt-1 items-center">
          <span className="text-xs">Delete this account?</span>
          <Button size="sm" variant="destructive" onClick={remove} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Yes, delete'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirmingDelete(false)} disabled={deleting}>
            Cancel
          </Button>
        </div>
      ) : (
        <div className="flex gap-2 pt-1">
          <Button size="sm" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" variant="outline" onClick={() => setConfirmingDelete(true)} disabled={saving}
            className="ml-auto text-destructive hover:bg-destructive/10">
            Delete
          </Button>
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
