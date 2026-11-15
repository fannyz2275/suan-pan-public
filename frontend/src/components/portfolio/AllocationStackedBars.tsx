// frontend/src/components/portfolio/AllocationStackedBars.tsx
import { useEffect, useState } from "react";
import { type ExposureSlice, fetchExposure } from "../../lib/portfolio";

type Dim = "asset_class" | "sector" | "region" | "country";

type Props = {
  accountId?: string;
  onSelect?: (dim: Dim, label: string | null) => void;
};

const DIM_LABELS: Record<Dim, string> = {
  asset_class: "Asset class",
  sector: "Sector",
  region: "Region",
  country: "Country",
};

const DIM_ORDER: Dim[] = ["asset_class", "sector", "country", "region"];

const PALETTE = ["#1f6feb", "#3fb950", "#f0883e", "#d29922", "#a371f7", "#8b949e", "#bf8700", "#39d353"];

export default function AllocationStackedBars({ accountId, onSelect }: Props) {
  const [byDim, setByDim] = useState<Record<Dim, ExposureSlice[]>>({
    asset_class: [], sector: [], region: [], country: [],
  });
  const [active, setActive] = useState<{ dim: Dim; label: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchExposure("asset_class", accountId),
      fetchExposure("sector", accountId),
      fetchExposure("region", accountId),
      fetchExposure("country", accountId),
    ]).then(([ac, sec, reg, ctry]) => {
      if (cancelled) return;
      setByDim({ asset_class: ac, sector: sec, region: reg, country: ctry });
    });
    return () => { cancelled = true; };
  }, [accountId]);

  const bar = (dim: Dim) => (
    <div key={dim} data-testid={`bar-${dim}`} className="mb-3">
      <div className="text-xs text-gray-600 font-semibold uppercase tracking-wide mb-1">
        {DIM_LABELS[dim]}
      </div>
      <div className="flex h-7 rounded overflow-hidden text-[11px] text-white font-semibold">
        {byDim[dim].map((s, idx) => {
          const isActive = active?.dim === dim && active.label === s.label;
          const isOther = active && (active.dim !== dim || active.label !== s.label);
          return (
            <div
              key={s.label}
              role="button"
              onClick={() => {
                const next = isActive ? null : { dim, label: s.label };
                setActive(next);
                onSelect?.(dim, next?.label ?? null);
              }}
              style={{
                background: PALETTE[idx % PALETTE.length],
                flex: s.percent,
                opacity: isOther ? 0.4 : 1,
              }}
              className="flex items-center justify-center cursor-pointer hover:brightness-110"
              title={`${s.label}: ${s.percent.toFixed(1)}%`}
            >
              {s.percent >= 6 ? `${s.label} ${s.percent.toFixed(0)}%` : ""}
            </div>
          );
        })}
      </div>
    </div>
  );

  // A dim that's just one "Other" slice carries no information — hide it.
  const informative = (slices: ExposureSlice[]) =>
    slices.length > 0 && !(slices.length === 1 && slices[0].label === "Other");
  const visibleDims = DIM_ORDER.filter((d) => informative(byDim[d]));
  if (visibleDims.length === 0) return null;

  const allOtherDims = DIM_ORDER.filter(
    (d) => byDim[d].length === 1 && byDim[d][0].label === "Other",
  );

  return (
    <div data-testid="allocation-bars" className="bg-white p-4 rounded shadow">
      <h3 className="font-semibold text-gray-900 mb-3">Allocation</h3>
      {visibleDims.map((d) => bar(d))}
      {allOtherDims.length > 0 && (
        <div data-testid="allocation-other-note" className="text-xs text-gray-500 mt-2">
          Hiding {allOtherDims.map((d) => DIM_LABELS[d].toLowerCase()).join(", ")} —
          your tickers don't have classification metadata yet (mutual funds and
          some ETFs don't expose this through yfinance).
        </div>
      )}
    </div>
  );
}
