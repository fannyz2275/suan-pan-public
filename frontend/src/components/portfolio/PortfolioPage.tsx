// frontend/src/components/portfolio/PortfolioPage.tsx
import { useEffect, useState } from "react";
import AccountScopeChips from "./AccountScopeChips";
import AllocationStackedBars from "./AllocationStackedBars";
import HoldingsTable from "./HoldingsTable";
import LookThroughTopHoldings from "./LookThroughTopHoldings";
import UnifiedImportModal from "../UnifiedImportModal";
import PortfolioTimeSeriesChart from "./PortfolioTimeSeriesChart";
import { WINDOWS, windowToRange } from "./windowRange";
import { fetchPortfolioValue, syncPlaidInvestments, type PortfolioValue } from "../../lib/portfolio";

const fmtCurrency = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export default function PortfolioPage() {
  const [accountId, setAccountId] = useState<string | undefined>(undefined);
  const [importOpen, setImportOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [windowKey, setWindowKey] = useState<string>("3M");
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [value, setValue] = useState<PortfolioValue | null>(null);

  const { from, to } = windowToRange(windowKey);

  useEffect(() => {
    let cancelled = false;
    fetchPortfolioValue(accountId)
      .then((v) => { if (!cancelled) setValue(v); })
      .catch(() => { if (!cancelled) setValue(null); });
    return () => { cancelled = true; };
  }, [accountId, refreshKey]);

  async function handleSync() {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const result = await syncPlaidInvestments();
      setSyncMsg(`Synced — ${result.snapshots_written} snapshot${result.snapshots_written === 1 ? "" : "s"} written`);
      setRefreshKey((k) => k + 1);
    } catch {
      setSyncMsg("Sync failed — check Plaid connection");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div data-testid="portfolio-page" className="space-y-4">
      <div data-testid="portfolio-headline" className="bg-white p-4 rounded shadow">
        <div className="text-xs text-gray-500 uppercase tracking-wide">
          {accountId ? "Account value" : "Total portfolio value"}
        </div>
        <div className="text-3xl font-semibold text-gray-900">
          {value ? fmtCurrency(value.total_value) : "—"}
        </div>
        {value?.as_of && (
          <div className="text-xs text-gray-500 mt-1">
            as of {value.as_of}
            {!accountId && value.account_count > 0 && ` · ${value.account_count} account${value.account_count === 1 ? "" : "s"}`}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between">
        <AccountScopeChips selectedAccountId={accountId} onChange={setAccountId} />
        <div className="flex items-center gap-2">
          {syncMsg && (
            <span data-testid="sync-status-msg" className="text-xs text-gray-500">{syncMsg}</span>
          )}
          <button
            data-testid="btn-sync-plaid"
            onClick={handleSync}
            disabled={syncing}
            className="px-3 py-2 text-sm rounded bg-gray-100 text-gray-700 disabled:opacity-50"
          >
            {syncing ? "Syncing…" : "Sync Plaid"}
          </button>
          <button
            data-testid="btn-import-statement"
            onClick={() => setImportOpen(true)}
            className="px-3 py-2 text-sm rounded bg-gray-900 text-white"
          >
            Import statement
          </button>
        </div>
      </div>
      <div className="flex gap-1">
        {Object.keys(WINDOWS).map((w) => (
          <button
            key={w}
            data-testid={`window-btn-${w}`}
            className={`px-2 py-1 text-xs rounded ${
              windowKey === w ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-700"
            }`}
            onClick={() => setWindowKey(w)}
          >
            {w}
          </button>
        ))}
      </div>
      <PortfolioTimeSeriesChart
        key={`chart-${refreshKey}`}
        accountId={accountId}
        fromDate={from}
        toDate={to}
      />
      <AllocationStackedBars key={`alloc-${refreshKey}`} accountId={accountId} />
      <LookThroughTopHoldings key={`lookthrough-${refreshKey}`} accountId={accountId} />
      <HoldingsTable key={`hold-${refreshKey}`} accountId={accountId} />

      {importOpen && (
        <UnifiedImportModal
          onClose={() => setImportOpen(false)}
          onImported={() => setRefreshKey((k) => k + 1)}
          onRequestReview={() => { /* portfolio page does not own the review modal */ }}
          initialAccountId={accountId}
        />
      )}
    </div>
  );
}
