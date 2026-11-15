export interface AccountLabelInput {
  name?: string | null
  nickname?: string | null
  account_number_last4?: string | null
}

export function formatAccountLabel(a: AccountLabelInput): string {
  const base = a.nickname || a.name || '(unnamed)'
  const last4 = a.account_number_last4 && /^\d{4}$/.test(a.account_number_last4)
    ? a.account_number_last4
    : null
  return last4 ? `${base} (*${last4})` : base
}
