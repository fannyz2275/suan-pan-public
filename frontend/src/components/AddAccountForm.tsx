import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { accountsApi } from '@/lib/api'
import { EditFields, NicknameAndLast4Fields } from './AccountLeafEdit'
import type { Account } from '@/lib/types'

const TYPES: Array<{ value: string; label: string }> = [
  { value: 'checking', label: 'Checking' },
  { value: 'savings', label: 'Savings' },
  { value: 'brokerage', label: 'Brokerage' },
  { value: 'retirement', label: 'Retirement' },
  { value: 'property', label: 'Property' },
  { value: 'rsu', label: 'RSU' },
  { value: 'business', label: 'Business' },
  { value: 'debt', label: 'Debt' },
]

const NUMERIC_FIELDS = new Set<keyof Account>([
  'balance', 'estimated_value', 'purchase_price', 'vested_shares',
  'unvested_shares', 'grant_price', 'ownership_pct', 'estimated_valuation',
  'liquidity_horizon_months',
])

interface Props {
  onSaved: () => void
  onCancel: () => void
}

export default function AddAccountForm({ onSaved, onCancel }: Props) {
  const [draft, setDraft] = useState<Account>({
    id: '',
    type: 'checking',
    name: '',
    balance: 0,
    nickname: null,
    account_number_last4: null,
  } as Account)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleChange = (field: keyof Account, value: string) => {
    setDraft((prev) => ({
      ...prev,
      [field]: NUMERIC_FIELDS.has(field) ? (value === '' ? null : Number(value)) : value,
    }))
  }
  const handlePatch = (patch: Partial<Account>) => setDraft((prev) => ({ ...prev, ...patch }))

  const submit = async () => {
    setError(null)
    if (!draft.name?.trim()) {
      setError('Name is required.')
      return
    }
    if (draft.account_number_last4 && !/^\d{4}$/.test(draft.account_number_last4)) {
      setError('Last 4 digits must be exactly 4 digits.')
      return
    }
    setSaving(true)
    try {
      const { id: _id, ...payload } = draft
      await accountsApi.create(payload)
      onSaved()
    } catch {
      setError('Failed to create account. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">New account</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <Label className="text-xs" htmlFor="add-account-type">Type</Label>
            <select
              id="add-account-type"
              className="h-7 text-sm border rounded px-2 w-full bg-background"
              value={draft.type}
              onChange={(e) => setDraft((prev) => ({ ...prev, type: e.target.value as Account['type'] }))}
            >
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <NicknameAndLast4Fields
            nickname={draft.nickname}
            last4={draft.account_number_last4}
            onChange={handlePatch}
            idPrefix="add-account"
          />
          <EditFields draft={draft} onChange={handleChange} idPrefix="add-account" />
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={submit} disabled={saving}>
            {saving ? 'Saving…' : 'Save account'}
          </Button>
          <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </CardContent>
    </Card>
  )
}
