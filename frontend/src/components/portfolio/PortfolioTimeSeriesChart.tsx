// frontend/src/components/portfolio/PortfolioTimeSeriesChart.tsx
import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fetchTimeSeries, type TimeSeriesPoint } from "../../lib/portfolio";

type Props = {
  accountId?: string;
  fromDate: string;
  toDate: string;
};

export default function PortfolioTimeSeriesChart({ accountId, fromDate, toDate }: Props) {
  const [data, setData] = useState<TimeSeriesPoint[]>([]);
  const [completedRequest, setCompletedRequest] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestKey = JSON.stringify([fromDate, toDate, accountId]);
  const loading = completedRequest !== requestKey;
  const [unpriced, setUnpriced] = useState<string[]>([]);
  const [snapshotDates, setSnapshotDates] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchTimeSeries(fromDate, toDate, accountId)
      .then((d) => {
        if (!cancelled) {
          setError(null);
          setData(d.series);
          setUnpriced(d.unpriced_tickers ?? []);
          setSnapshotDates(d.snapshot_dates ?? []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setData([]);
          setUnpriced([]);
          setSnapshotDates([]);
          setError("Could not load portfolio values.");
        }
      })
      .finally(() => { if (!cancelled) setCompletedRequest(requestKey); });
    return () => { cancelled = true; };
  }, [fromDate, toDate, accountId, requestKey]);

  const snapshotSet = useMemo(() => new Set(snapshotDates), [snapshotDates]);
  const lastSnapshot = snapshotDates[snapshotDates.length - 1];

  // Split the value series into two: a solid run up to the latest snapshot,
  // and a dashed extrapolation beyond it. We render two <Line>s sharing the
  // same data — each masks itself with null on the inactive segment so a
  // single visual line is drawn with two stroke styles.
  const solidData = useMemo(
    () => data.map((p) => ({
      ...p,
      solid: lastSnapshot && p.date <= lastSnapshot ? p.total_value : null,
    })),
    [data, lastSnapshot],
  );
  const dashedData = useMemo(
    () => data.map((p) => ({
      ...p,
      dashed: lastSnapshot && p.date >= lastSnapshot ? p.total_value : null,
    })),
    [data, lastSnapshot],
  );
  const hasExtrapolation = !!lastSnapshot
    && data.length > 0
    && data[data.length - 1].date > lastSnapshot;

  return (
    <div data-testid="timeseries-chart" className="bg-white p-4 rounded shadow">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-900">Portfolio value</h3>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={solidData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={32} />
          <YAxis yAxisId="left" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
          <Tooltip
            formatter={(v) =>
              Number(v ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" })
            }
          />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="solid"
            stroke="#1f6feb"
            strokeWidth={2}
            connectNulls={false}
            isAnimationActive={false}
            dot={(dotProps: { cx?: number; cy?: number; payload?: { date?: string } }) => {
              const { cx, cy, payload } = dotProps;
              if (cx == null || cy == null || !payload?.date || !snapshotSet.has(payload.date)) {
                return <g />;
              }
              return (
                <circle
                  cx={cx} cy={cy} r={3.5}
                  fill="#1f6feb" stroke="#fff" strokeWidth={1.5}
                />
              );
            }}
            activeDot={{ r: 4 }}
          />
          <Line
            yAxisId="left"
            type="monotone"
            data={dashedData}
            dataKey="dashed"
            stroke="#1f6feb"
            strokeWidth={2}
            strokeDasharray="4 3"
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      {loading && <div className="text-xs text-gray-500 mt-2">Loading…</div>}
      {!loading && error && <p role="alert" className="text-sm text-red-600 mt-2">{error}</p>}
      {!loading && !error && data.length === 0 && (
        <div className="text-sm text-gray-500 mt-2">
          No snapshots in this window. Add a manual snapshot to get started.
        </div>
      )}
      {!loading && (hasExtrapolation || snapshotDates.length > 0) && (
        <div className="mt-2 text-[11px] text-gray-500 flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block w-3 h-[2px] bg-[#1f6feb]" />
            Daily mark
          </span>
          <span className="inline-flex items-center gap-1">
            <span
              className="inline-block w-3 h-[2px]"
              style={{ background: "repeating-linear-gradient(90deg,#1f6feb 0 4px,transparent 4px 7px)" }}
            />
            Held flat after last snapshot
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="inline-block w-2 h-2 rounded-full bg-[#1f6feb] border border-white shadow-[0_0_0_1px_#1f6feb]" />
            Statement snapshot
          </span>
        </div>
      )}
      {!loading && unpriced.length > 0 && (
        <div
          data-testid="unpriced-warning"
          className="mt-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-2 space-y-1"
        >
          <div>
            ⚠ {unpriced.length} ticker{unpriced.length === 1 ? "" : "s"} held flat —
            our market-data source (yfinance) doesn't carry daily prices for{" "}
            {unpriced.length === 1 ? "it" : "them"}. This is common for mutual funds
            and delisted/renamed symbols:{" "}
            <span className="font-mono">{unpriced.join(", ")}</span>.
          </div>
          <div className="text-amber-700">
            Best fix: link this account via <b>Plaid</b> (Connect option in the
            Import dialog, or the "Connect bank" button on the Accounts tab) —
            your brokerage provides its own daily marks, so the snapshot stays
            fresh without needing public price data. Alternatives: import a more
            recent statement, or correct a renamed ticker.
          </div>
        </div>
      )}
    </div>
  );
}
