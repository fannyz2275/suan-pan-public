// frontend/src/lib/portfolio.ts
import api from "./api";

export type Holding = {
  ticker: string;
  name?: string;
  quantity: number;
  price: number;
  market_value: number;
  percent: number;
  cost_basis?: number | null;
  unrealized_gain?: number | null;
};

export type ExposureSlice = {
  label: string;
  market_value: number;
  percent: number;
};

export type TimeSeriesPoint = {
  date: string;
  total_value: number;
};

export type ManualHolding = {
  ticker: string;
  quantity: number;
  price: number;
  cost_basis?: number;
};

const accountParam = (accountId?: string) =>
  accountId ? `&account_id=${accountId}` : "";

export async function fetchHoldings(accountId?: string) {
  const r = await api.get<Holding[]>(
    `/portfolio/holdings?${accountParam(accountId).slice(1)}`
  );
  return r.data;
}

export async function fetchExposure(
  dim: "asset_class" | "sector" | "region" | "country",
  accountId?: string
) {
  const r = await api.get<ExposureSlice[]>(
    `/portfolio/exposure?dim=${dim}${accountParam(accountId)}`
  );
  return r.data;
}

export type LookThroughHolding = {
  ticker: string;
  name: string | null;
  sector: string | null;
  country: string | null;
  market_value: number;
  percent: number;
  via: string[];
};

export async function fetchLookThrough(
  limit = 10,
  accountId?: string,
): Promise<LookThroughHolding[]> {
  const r = await api.get<LookThroughHolding[]>(
    `/portfolio/lookthrough?limit=${limit}${accountParam(accountId)}`,
  );
  return r.data;
}

export type MacroOverlayPoint = {
  date: string;
  ten_year_yield: number | null;
  cpi_yoy: number | null;
  spy_close: number | null;
};

export type TimeSeriesResponse = {
  series: TimeSeriesPoint[];
  overlays: MacroOverlayPoint[];
  unpriced_tickers?: string[];
  snapshot_dates?: string[];
};

export type PortfolioValue = {
  total_value: number;
  as_of: string | null;
  account_count: number;
};

export async function fetchPortfolioValue(accountId?: string): Promise<PortfolioValue> {
  const r = await api.get<PortfolioValue>(
    `/portfolio/value?${accountParam(accountId).slice(1)}`,
  );
  return r.data;
}

export async function fetchTimeSeries(
  fromDate: string,
  toDate: string,
  accountId?: string
): Promise<TimeSeriesResponse> {
  const r = await api.get<TimeSeriesResponse>(
    `/portfolio/timeseries?from_date=${fromDate}&to_date=${toDate}${accountParam(accountId)}`
  );
  return r.data;
}

export type MacroContext = {
  ten_year_yield_change_bps: number | null;
  cpi_yoy_at_end: number | null;
  spy_period_return_pct: number | null;
};

export type AttributionResult = {
  from_date: string;
  to_date: string;
  start_value: number;
  end_value: number;
  contributions: number;
  withdrawals: number;
  dividends: number;
  trades: number;
  trades_has_basis: boolean;
  market: number;
  unattributed: number;
  macro_context: MacroContext | null;
};

export async function fetchAttribution(
  fromDate: string,
  toDate: string,
  accountId?: string
) {
  const r = await api.get<AttributionResult>(
    `/portfolio/attribution?from_date=${fromDate}&to_date=${toDate}${accountParam(accountId)}`
  );
  return r.data;
}

export async function createManualSnapshot(payload: {
  account_id: string;
  snapshot_date: string;
  cash_value: number;
  holdings: ManualHolding[];
}) {
  const r = await api.post(`/portfolio/snapshot/manual`, payload);
  return r.data;
}

export type StatementHolding = {
  ticker: string;
  name?: string | null;
  quantity: number;
  price: number;
  market_value: number;
  cost_basis?: number | null;
};

export type StatementInvestmentTxn = {
  date: string;
  type:
    | "buy" | "sell" | "dividend" | "interest" | "fee"
    | "transfer_in" | "transfer_out" | "split" | "reinvest";
  ticker?: string | null;
  quantity?: number | null;
  price?: number | null;
  amount: number;
};

export type StatementPreview = {
  statement_date: string;
  cash_value: number;
  account_hint?: string | null;
  total_value_reported?: number | null;
  holdings: StatementHolding[];
  investment_transactions: StatementInvestmentTxn[];
};

export async function previewStatement(text: string) {
  const r = await api.post<StatementPreview>("/portfolio/import/statement", { text });
  return r.data;
}

export async function previewStatementFile(file: File) {
  const form = new FormData();
  form.append("file", file);
  const r = await api.post<StatementPreview>(
    "/portfolio/import/statement/file",
    form,
    // No explicit Content-Type — axios sets it (with boundary) from FormData.
  );
  return r.data;
}

export async function confirmStatementImport(payload: {
  account_id: string;
  statement_date: string;
  cash_value: number;
  holdings: StatementHolding[];
  investment_transactions: StatementInvestmentTxn[];
}) {
  const r = await api.post(`/portfolio/import/statement/confirm`, payload);
  return r.data;
}

export async function syncPlaidInvestments() {
  const r = await api.post<{ snapshots_written: number }>("/portfolio/sync/plaid");
  return r.data;
}
