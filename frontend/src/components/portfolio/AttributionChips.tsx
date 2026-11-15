import type { AttributionResult } from "../../lib/portfolio";

const fmt = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

type ChipDef = { label: string; value: number; positive: boolean };

export default function AttributionChips({ data }: { data: AttributionResult }) {
  const chips: ChipDef[] = [];
  const push = (label: string, value: number) => {
    if (Math.abs(value) >= 100 || (label === "Dividends" && Math.abs(value) >= 10)) {
      chips.push({ label, value, positive: value >= 0 });
    }
  };
  push("Market", data.market);
  push("Contributions", data.contributions);
  push("Withdrawals", data.withdrawals);
  push("Dividends", data.dividends);
  push("Trades" + (data.trades_has_basis ? "" : " (no basis)"), data.trades);
  push("Unattributed", data.unattributed);

  const periodChange = data.end_value - data.start_value;

  return (
    <div data-testid="attribution-chips" className="space-y-2 mb-2">
      <div data-testid="attribution-chips-period" className="text-xs text-gray-600">
        {data.from_date} → {data.to_date} ·{" "}
        <span className={periodChange >= 0 ? "text-green-700 font-semibold" : "text-red-700 font-semibold"}>
          {periodChange >= 0 ? "+" : ""}{fmt(periodChange)}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {chips.map((c) => (
          <span
            key={c.label}
            className={`px-2 py-1 text-xs rounded font-semibold ${
              c.positive
                ? "bg-green-50 text-green-800 border border-green-200"
                : "bg-red-50 text-red-800 border border-red-200"
            }`}
          >
            {c.label} {c.positive ? "+" : ""}{fmt(c.value)}
          </span>
        ))}
      </div>
    </div>
  );
}
