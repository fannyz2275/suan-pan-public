import { useEffect, useMemo, useState } from "react";
import { type Holding, fetchHoldings } from "../../lib/portfolio";

type SortKey = "ticker" | "quantity" | "market_value" | "percent";

type Props = { accountId?: string };

export default function HoldingsTable({ accountId }: Props) {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("market_value");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    let cancelled = false;
    fetchHoldings(accountId).then((d) => !cancelled && setHoldings(d));
    return () => { cancelled = true; };
  }, [accountId]);

  const sorted = useMemo(() => {
    const arr = [...holdings];
    arr.sort((a, b) => {
      const av = a[sortKey] as number | string;
      const bv = b[sortKey] as number | string;
      if (av === bv) return 0;
      const cmp = av > bv ? 1 : -1;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [holdings, sortKey, sortDir]);

  const toggle = (k: SortKey) => {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(k); setSortDir("desc"); }
  };

  return (
    <div data-testid="holdings-table" className="bg-white p-4 rounded shadow">
      <h3 className="font-semibold text-gray-900 mb-3">Holdings</h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-600 border-b">
            <Th onClick={() => toggle("ticker")} active={sortKey === "ticker"} dir={sortDir} testId="col-ticker">Ticker</Th>
            <Th onClick={() => toggle("quantity")} active={sortKey === "quantity"} dir={sortDir} right testId="col-quantity">Qty</Th>
            <Th onClick={() => toggle("market_value")} active={sortKey === "market_value"} dir={sortDir} right testId="col-market-value">Market value</Th>
            <Th onClick={() => toggle("percent")} active={sortKey === "percent"} dir={sortDir} right testId="col-percent">% of port</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((h) => (
            <tr key={h.ticker} data-testid={`holding-row-${h.ticker}`} className="border-b last:border-0">
              <td className="py-2 font-mono">{h.ticker}</td>
              <td className="py-2 text-right">{h.quantity.toFixed(4)}</td>
              <td className="py-2 text-right">
                {h.market_value.toLocaleString("en-US", { style: "currency", currency: "USD" })}
              </td>
              <td className="py-2 text-right">{h.percent.toFixed(1)}%</td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr><td colSpan={4} className="py-3 text-center text-gray-500">No holdings yet.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  onClick, active, dir, right, testId, children,
}: {
  onClick: () => void; active: boolean; dir: "asc" | "desc"; right?: boolean;
  testId: string; children: React.ReactNode;
}) {
  return (
    <th
      data-testid={testId}
      onClick={onClick}
      className={`py-2 cursor-pointer select-none ${right ? "text-right" : ""}`}
    >
      {children}
      {active && <span className="ml-1 text-gray-400">{dir === "asc" ? "▲" : "▼"}</span>}
    </th>
  );
}
