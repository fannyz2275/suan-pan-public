import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import AccountsTree from './AccountsTree'
import AddAccountForm from './AddAccountForm'
import PlaidConnectButton from './PlaidConnectButton'
import type { Account, NetWorthNode } from '@/lib/types'

interface Props {
  accounts: Account[]
  tree: NetWorthNode | null
  onRefresh: () => void
}

export default function AccountsCard({ accounts, tree, onRefresh }: Props) {
  const [adding, setAdding] = useState(false)
  const accountsById = useMemo(
    () => Object.fromEntries(accounts.map((a) => [a.id, a])),
    [accounts]
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <PlaidConnectButton onConnected={onRefresh} />
        <Button size="sm" variant={adding ? 'ghost' : 'default'} onClick={() => setAdding((v) => !v)}>
          {adding ? 'Close' : '+ Add account'}
        </Button>
      </div>

      {adding && (
        <AddAccountForm
          onSaved={() => { setAdding(false); onRefresh() }}
          onCancel={() => setAdding(false)}
        />
      )}

      <AccountsTree tree={tree} accountsById={accountsById} onChanged={onRefresh} />

      {accounts.length === 0 && !adding && (
        <p className="text-sm text-muted-foreground text-center py-8">
          No accounts yet — click "+ Add account" to start.
        </p>
      )}
    </div>
  )
}
