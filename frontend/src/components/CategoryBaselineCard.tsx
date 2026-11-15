import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCurrency } from '@/lib/formatters'
import type { CashFlowResponse, CategoryBaseline } from '@/lib/types'

interface Props {
  snapshot: CashFlowResponse | null
  onEditBudget?: () => void
}

const TIER_LABELS: Record<string, string> = {
  T2: '3–4mo',
  T3: '5–11mo',
  T4: '12mo+',
}

function tierVariant(tier: CategoryBaseline['tier']): 'default' | 'secondary' {
  return tier === 'T4' ? 'default' : 'secondary'
}

export default function CategoryBaselineCard({ snapshot, onEditBudget }: Props) {
  if (!snapshot) return null
  const baselines = snapshot.category_baselines
  const warning = snapshot.expense_budget_warning
  if (baselines.length === 0 && !warning) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Spending baselines</CardTitle>
        <p className="text-xs text-muted-foreground">
          What we use to project your monthly expenses, based on your transaction history.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {warning && (
          <div className="border border-amber-300 bg-amber-50 rounded-md p-3 text-sm dark:bg-amber-950/30 dark:border-amber-800">
            <div className="font-medium mb-1">History exceeds your stated budget</div>
            <div className="text-xs text-muted-foreground mb-2">
              Last few months show ~{formatCurrency(warning.baselined_total)}/mo, but your profile says{' '}
              {formatCurrency(warning.stated_monthly_expenses)}/mo. Update your monthly expenses to
              improve projection accuracy.
            </div>
            {onEditBudget && (
              <button
                type="button"
                onClick={onEditBudget}
                className="text-xs underline"
              >
                Edit monthly expenses
              </button>
            )}
          </div>
        )}
        {baselines.length > 0 && (
          <div className="text-sm">
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 gap-y-1 items-center">
              <div className="text-xs text-muted-foreground uppercase tracking-wide">Category</div>
              <div className="text-xs text-muted-foreground uppercase tracking-wide">Tier</div>
              <div className="text-xs text-muted-foreground uppercase tracking-wide text-right">Median</div>
              <div className="text-xs text-muted-foreground uppercase tracking-wide text-right">Next mo</div>
              {baselines.map((b) => (
                <BaselineRow key={b.category} b={b} />
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Residual lump (categories with thin data + everything else):{' '}
              <span className="text-foreground font-medium">
                {formatCurrency(snapshot.residual_monthly_expenses)}
              </span>
              /mo
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function BaselineRow({ b }: { b: CategoryBaseline }) {
  return (
    <>
      <div className="capitalize">{b.category}</div>
      <div>
        <Badge variant={tierVariant(b.tier)} className="text-xs">
          {TIER_LABELS[b.tier] ?? b.tier}
        </Badge>
      </div>
      <div className="text-right tabular-nums">{formatCurrency(b.median_monthly)}</div>
      <div className="text-right tabular-nums">
        {formatCurrency(b.next_month_expected)}
        {b.seasonal_multiplier ? (
          <span className="text-xs text-muted-foreground ml-1">×{b.seasonal_multiplier.toFixed(2)}</span>
        ) : null}
      </div>
    </>
  )
}
