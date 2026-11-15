import type { CashFlowResponse } from '@/lib/types'
import { formatCurrency } from '@/lib/formatters'
export default function CashOutlook({ cash, forecast, monthlyExpenses }: { cash: number | null; forecast: CashFlowResponse | null; monthlyExpenses: number | null }) {
  const expensesKnown = monthlyExpenses !== null && Number.isFinite(monthlyExpenses) && monthlyExpenses > 0
  const cashKnown = cash !== null && Number.isFinite(cash)
  const coverage = cashKnown && expensesKnown ? Math.max(0, cash) / monthlyExpenses : null
  const months = forecast?.cashflow.slice(0, 3) ?? []
  const reliableInputs = cashKnown && forecast?.income_expense_history_available === true && months.length === 3 && months.every(m => Number.isFinite(m.balance))
  const shortfall = reliableInputs ? months.find(m => m.balance < 0) : undefined
  return <section aria-label="Cash outlook" className="space-y-3 border-b pb-5">
    <h2 className="text-base font-semibold">Cash outlook</h2>
    <p className="text-lg font-medium">{coverage === null ? 'Not enough spending history or cash data to estimate how long your cash could last.' : `Your available cash could cover about ${coverage.toFixed(1)} months of expenses.`}</p>
    {coverage !== null && <p className="text-xs text-muted-foreground">Based on {formatCurrency(cash!)} of recorded cash and typical monthly spending of {formatCurrency(monthlyExpenses!)}. Assumes no new income; this is not income coverage.</p>}
    {reliableInputs ? <>
      <p className="text-lg">In three months, you could have <strong>{formatCurrency(months[2].balance)}</strong> available.</p>
      {coverage === null && <p className="text-xs text-muted-foreground">This forecast uses a longer history window than the cash-coverage estimate above. Available records may be incomplete.</p>}
      <p className={shortfall ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'}>{shortfall ? `Cash could fall below zero in ${shortfall.month}, by ${formatCurrency(-shortfall.balance)}.` : 'No below-zero month-end balance is projected in the next three months. Bills can still cause shortfalls within a month.'}</p>
    </> : <p className="text-sm text-muted-foreground">Three-month outlook unavailable until cash balances and spending history are available.</p>}
    <details className="text-sm border-t pt-3"><summary className="cursor-pointer font-medium">Forecast assumptions</summary>
      <div className="mt-3 space-y-2 text-xs text-muted-foreground">
        <p>Recorded balances are not live bank balances. Income and spending estimates come from imported history, which may be incomplete or out of date. This forecast is an estimate, not a guarantee.</p>
        {forecast && <p>Typical monthly income used: {formatCurrency(forecast.monthly_income)}. Spending combines category estimates with remaining monthly expenses of {formatCurrency(forecast.residual_monthly_expenses)}.</p>}
        <p>Scheduled company-share vesting can be counted as cash at the recorded grant price. This assumes the shares can be sold; sale timing, taxes, and price changes are not modeled. Goal purchases and unexpected bills are not included in the base forecast.</p>
        {reliableInputs && <ul className="space-y-1">{months.map(m => <li key={m.month}>{m.month}: {formatCurrency(m.balance)} estimated month-end cash</li>)}</ul>}
      </div>
    </details>
  </section>
}
