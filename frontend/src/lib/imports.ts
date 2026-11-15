import api from './api'

export type Kind = 'bank' | 'investment'

export interface BankPreview {
  statement_date: string | null
  balance: number | null
  transactions: {
    date: string
    description: string
    amount: number
    category: string | null
  }[]
}

export interface InvestmentPreview {
  statement_date: string
  cash_value: number
  reported_cash_value?: number | null
  cash_in_holdings?: number
  holdings: {
    ticker: string
    quantity: number
    price: number
    market_value: number
    cost_basis?: number | null
    unrealized_gain?: number | null
  }[]
  investment_transactions: {
    date: string
    type: string
    ticker?: string | null
    quantity?: number | null
    price?: number | null
    amount: number
  }[]
  total_value_reported?: number | null
  account_hint?: string | null
}

export interface PreviewGroup {
  row_id: string
  account_id: string
  account_name: string
  account_type: string
  kind: Kind
  error: string | null
  preview: BankPreview | InvestmentPreview | null
  detected_last4?: string | null
  source_file?: string | null
  source_ranges?: number[][] | null
  error_code?: string | null
  document_notices?: { role: string; ranges: number[][]; excerpt?: string }[]
}

export interface PreviewResponse {
  groups: PreviewGroup[]
}

export interface UploadRow {
  rowId: string
  accountId: string
  files: File[]
}

export async function detectStatements(files: File[]): Promise<PreviewResponse> {
  const form = new FormData()
  for (const file of files) form.append('files', file, file.name)
  return (await api.post<PreviewResponse>('/import/statements/detect', form)).data
}

export async function previewStatements(rows: UploadRow[]): Promise<PreviewResponse> {
  const form = new FormData()
  form.append(
    'rows',
    JSON.stringify(rows.map((r) => ({ row_id: r.rowId, account_id: r.accountId }))),
  )
  for (const r of rows) {
    for (const f of r.files) form.append(r.rowId, f, f.name)
  }
  const res = await api.post<PreviewResponse>('/import/statements/preview', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export type BankConfirmGroup = {
  row_id: string
  account_id: string
  kind: 'bank'
  balance: number | null
  statement_date: string | null
  transactions: BankPreview['transactions']
}

export type InvestmentConfirmGroup = {
  row_id: string
  account_id: string
  kind: 'investment'
  statement_date: string
  cash_value: number
  holdings: InvestmentPreview['holdings']
  investment_transactions: InvestmentPreview['investment_transactions']
}

export type ConfirmGroup = (BankConfirmGroup | InvestmentConfirmGroup) & {
  detected_type?: string
  destination_confirmed?: boolean
}

export interface SavedRow {
  row_id: string
  account_id: string
  error: string | null
  transactions_created?: number
  transactions_skipped?: number
  balance_updated?: boolean
  snapshot_id?: string
  holdings_count?: number
  txns_count?: number
}

export interface ConfirmResponse {
  ok: boolean
  saved: SavedRow[]
  transfer_candidates_added: number
}

export async function confirmStatements(groups: ConfirmGroup[]): Promise<ConfirmResponse> {
  const res = await api.post<ConfirmResponse>('/import/statements/confirm', { groups })
  return res.data
}
