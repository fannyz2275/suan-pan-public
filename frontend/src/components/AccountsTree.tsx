import { useState } from 'react'
import { formatCurrency as fmt, formatShortDate } from '@/lib/formatters'
import { formatAccountLabel } from '@/lib/formatAccountLabel'
import { accountGroupLabel } from '@/lib/accountLabels'
import AccountLeafEdit from './AccountLeafEdit'
import type { Account, NetWorthNode } from '@/lib/types'

// Account types whose primary value is `balance`. For property/RSU/business
// the meaningful number lives elsewhere (estimated_value, vested_shares, …),
// so the "previous balance" line wouldn't be useful there.
const BALANCE_TYPES = new Set(['checking', 'savings', 'brokerage', 'retirement', 'debt'])

function BalanceHistoryLine({ account }: { account: Account }) {
  if (!BALANCE_TYPES.has(account.type)) return null
  const updated = formatShortDate(account.balance_updated_at)
  if (!updated) return null
  const hasPrevious =
    account.previous_balance != null && account.previous_balance_at != null
  const previousAt = hasPrevious ? formatShortDate(account.previous_balance_at) : null
  return (
    <p className="px-3 pb-1.5 text-[11px] text-muted-foreground">
      Updated {updated}
      {hasPrevious && previousAt && (
        <>
          {' · '}Previously {fmt(account.previous_balance as number)} on {previousAt}
        </>
      )}
    </p>
  )
}

interface Props {
  tree: NetWorthNode | null
  accountsById: Record<string, Account>
  onChanged: () => void
}

function Caret({ open }: { open: boolean }) {
  return (
    <span className={`inline-block w-3 transition-transform ${open ? 'rotate-90' : ''}`}>▸</span>
  )
}

function ClassNode({ node, accountsById, onChanged }: { node: NetWorthNode; accountsById: Record<string, Account>; onChanged: () => void }) {
  const [open, setOpen] = useState(true)
  const value = node.signed_value
  return (
    <div>
      <button
        type="button"
        className="flex items-center justify-between w-full px-3 py-2 hover:bg-muted/50 rounded text-sm font-medium"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flex items-center gap-2">
          <Caret open={open} />
          {accountGroupLabel(node.name)}
        </span>
        <span className={value < 0 ? 'text-destructive' : ''}>{fmt(value)}</span>
      </button>
      {open && node.children && (
        <div className="ml-4 mt-1 space-y-1">
          {node.children.map((t) => (
            <TypeNode key={t.id} node={t} accountsById={accountsById} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  )
}

function TypeNode({ node, accountsById, onChanged }: { node: NetWorthNode; accountsById: Record<string, Account>; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const value = node.signed_value
  return (
    <div>
      <button
        type="button"
        className="flex items-center justify-between w-full px-3 py-1.5 hover:bg-muted/50 rounded text-sm"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flex items-center gap-2 text-muted-foreground">
          <Caret open={open} />
          {accountGroupLabel(node.name)}
        </span>
        <span className={`text-muted-foreground ${value < 0 ? 'text-destructive' : ''}`}>{fmt(value)}</span>
      </button>
      {open && node.children && (
        <div className="ml-4 mt-1 space-y-1">
          {node.children.map((leaf) => (
            <AccountLeaf key={leaf.id} leaf={leaf} accountsById={accountsById} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  )
}

function AccountLeaf({ leaf, accountsById, onChanged }: { leaf: NetWorthNode; accountsById: Record<string, Account>; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const account = accountsById[leaf.id]
  const value = leaf.signed_value
  // Prefer the live `account` row's label so updates to nickname/last4 reflect
  // immediately without waiting for a tree refetch. Fall back to the
  // backend-rendered `leaf.name` (already formatted) when the account row
  // is missing from `accountsById`.
  const label = account ? formatAccountLabel(account) : leaf.name
  return (
    <div className="border rounded">
      <button
        type="button"
        className="flex items-center justify-between w-full px-3 py-1.5 hover:bg-muted/50 text-sm"
        onClick={() => setOpen((v) => !v)}
      >
        <span>{label}</span>
        <span className={value < 0 ? 'text-destructive' : ''}>{fmt(value)}</span>
      </button>
      {account && <BalanceHistoryLine account={account} />}
      {open && account && (
        <AccountLeafEdit
          account={account}
          onChanged={() => { onChanged(); setOpen(false) }}
          onCancel={() => setOpen(false)}
        />
      )}
      {open && !account && (
        <p className="px-3 py-2 text-xs text-muted-foreground">Account details unavailable.</p>
      )}
    </div>
  )
}

export default function AccountsTree({ tree, accountsById, onChanged }: Props) {
  if (!tree) {
    return <p className="text-sm text-muted-foreground py-4">Loading accounts…</p>
  }
  const classes = tree.children ?? []
  return (
    <div className="space-y-1">
      {classes.map((c) => (
        <ClassNode key={c.id} node={c} accountsById={accountsById} onChanged={onChanged} />
      ))}
    </div>
  )
}
