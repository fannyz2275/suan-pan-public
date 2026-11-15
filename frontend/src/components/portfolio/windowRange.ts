export const WINDOWS: Record<string, number> = {
  "1M": 30, "3M": 90, "6M": 180, "YTD": 0, "1Y": 365, "All": 365 * 10,
};

export function windowToRange(windowKey: string): { from: string; to: string } {
  const today = new Date();
  let from: Date;
  if (windowKey === "YTD") {
    from = new Date(today.getFullYear(), 0, 1);
  } else {
    from = new Date(today);
    from.setDate(today.getDate() - WINDOWS[windowKey]);
  }
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  return { from: fmt(from), to: fmt(today) };
}
