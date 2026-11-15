import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { formatCurrency as fmt } from '@/lib/formatters'
import type { NetWorthNode, Snapshot } from '@/lib/types'
import { accountGroupLabel } from '@/lib/accountLabels'

interface Props {
  snapshot: Snapshot
  tree?: NetWorthNode | null
}

function Row({ label, value, muted }: { label: string; value: number; muted?: boolean }) {
  return (
    <div className={`flex justify-between py-1 ${muted ? 'text-muted-foreground text-sm' : ''}`}>
      <span>{label}</span>
      <span className={value < 0 ? 'text-destructive' : ''}>{fmt(value)}</span>
    </div>
  )
}

function TreeRows({ tree }: { tree: NetWorthNode }) {
  // Render the four class-level children using their signed_value so
  // Liabilities shows up negative without per-class branching here.
  const classes = tree.children ?? []
  return (
    <>
      <div className="pb-3">
        {classes.map((c) => (
          <Row key={c.id} label={accountGroupLabel(c.name)} value={c.signed_value} muted />
        ))}
      </div>
      <div className="pt-3 space-y-1">
        <Row label="What you own minus what you owe" value={tree.signed_value} />
      </div>
    </>
  )
}

function LegacyRows({ snapshot }: { snapshot: Snapshot }) {
  return (
    <>
      <div className="pb-3">
        <Row label="Cash you can use" value={snapshot.liquid_assets} muted />
        <Row label="Investments" value={snapshot.investment_assets} muted />
        <Row label="Property and other assets" value={snapshot.non_current_assets} muted />
        <Row label="What you owe" value={-snapshot.total_liabilities} muted />
      </div>
      <div className="pt-3 space-y-1">
        <Row label="Cash and investments" value={snapshot.liquid_net_worth} />
        <Row label="What you own minus what you owe" value={snapshot.net_worth} />
      </div>
    </>
  )
}

export default function NetWorthCard({ snapshot, tree }: Props) {
  const headerValue = tree ? tree.signed_value : snapshot.net_worth
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle>Net Worth</CardTitle>
          <Badge variant="secondary">{fmt(headerValue)}</Badge>
        </div>
      </CardHeader>
      <CardContent className="divide-y">
        {tree ? <TreeRows tree={tree} /> : <LegacyRows snapshot={snapshot} />}
      </CardContent>
    </Card>
  )
}
