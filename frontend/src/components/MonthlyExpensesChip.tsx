import { formatCurrency } from '@/lib/formatters'
import type { ExpenseStatistic } from '@/lib/api'

interface Props {
  statistic: ExpenseStatistic | null
}

/**
 * Displays the user's monthly expenses inferred from transaction history.
 * The "Actual" branch (user-typed override on the profile) was removed
 * with the dollar-amount rule — Tier 1 no longer carries dollar amounts;
 * everything money-shaped now flows from the statistics path.
 */
export default function MonthlyExpensesChip({ statistic }: Props) {
  const hasStatistic = statistic?.source === 'computed' && statistic.value !== null

  if (hasStatistic) {
    const tooltip = `Average from your past ${statistic!.window_days} days of expense transactions (${statistic!.sample_size} transactions).`
    return (
      <span>
        {formatCurrency(statistic!.value!)}/mo expenses{' '}
        <span
          title={tooltip}
          className="text-[10px] leading-none px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-900 ring-1 ring-blue-300 ml-1"
        >
          Statistics
        </span>
      </span>
    )
  }
  return (
    <span className="text-muted-foreground">
      —/mo expenses{' '}
      <span
        title="Import enough transaction history to compute one."
        className="text-[10px] leading-none px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground ring-1 ring-border ml-1"
      >
        Not set
      </span>
    </span>
  )
}
