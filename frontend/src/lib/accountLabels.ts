const labels: Record<string, string> = {
  'Liquid Assets': 'Cash you can use',
  'Non-current Assets': 'Property and other assets',
  Liabilities: 'What you owe',
  Debt: 'Loans and other debts',
}
export const accountGroupLabel = (name: string) => labels[name] ?? name
