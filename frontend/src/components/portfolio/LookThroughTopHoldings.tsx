// frontend/src/components/portfolio/LookThroughTopHoldings.tsx
import { useEffect, useState } from "react";
import { fetchLookThrough, type LookThroughHolding } from "../../lib/portfolio";

type Props = {
  accountId?: string;
  limit?: number;
};

const fmtCurrency = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export default function LookThroughTopHoldings({ accountId, limit = 10 }: Props) {
  return <LookThroughResults key={JSON.stringify([accountId, limit])} accountId={accountId} limit={limit} />;
}

function LookThroughResults({ accountId, limit = 10 }: Props) {
  const [rows, setRows] = useState<LookThroughHolding[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchLookThrough(limit, accountId)
      .then((d) => { if (!cancelled) setRows(d); })
      .catch(() => { if (!cancelled) { setRows([]); setError("Could not load look-through holdings."); } });
    return () => { cancelled = true; };
  }, [accountId, limit]);

  if (rows === null) {
    return (
      <div data-testid="lookthrough-loading" className="bg-white p-4 rounded shadow text-sm text-gray-500">
        Loading top equity exposures…
      </div>
    );
  }

  return (
    <div data-testid="lookthrough-table" className="bg-white p-4 rounded shadow">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="font-semibold text-gray-900">Top equity exposures (look-through)</h3>
        <span className="text-xs text-gray-500">
          ETFs + mutual funds flattened to underlying stocks · cash & bonds excluded
        </span>
      </div>
      {error && <p className="text-xs text-red-600 mb-2">{error}</p>}
      {rows.length === 0 ? (
        <p className="text-sm text-gray-500">
          No look-through data yet. Add an ETF or mutual fund holding (we pull
          underlying composition from Yahoo Finance when available).
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-gray-500 border-b text-xs uppercase tracking-wide">
              <tr>
                <th className="py-1.5 text-left">Ticker</th>
                <th className="py-1.5 text-left">Name</th>
                <th className="py-1.5 text-left">Sector</th>
                <th className="py-1.5 text-left">Country</th>
                <th className="py-1.5 text-right">Market value</th>
                <th className="py-1.5 text-right">%</th>
                <th className="py-1.5 text-left">Held via</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ticker} className="border-b last:border-0 hover:bg-gray-50">
                  <td className="py-1.5 font-mono">{r.ticker}</td>
                  <td className="py-1.5 truncate max-w-[200px]">{r.name ?? "—"}</td>
                  <td className="py-1.5">{r.sector ?? "—"}</td>
                  <td className="py-1.5">{r.country ?? "—"}</td>
                  <td className="py-1.5 text-right">{fmtCurrency(r.market_value)}</td>
                  <td className="py-1.5 text-right">{r.percent.toFixed(2)}%</td>
                  <td className="py-1.5 text-xs text-gray-500 font-mono">
                    {r.via.length === 0 ? "direct" : r.via.join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
