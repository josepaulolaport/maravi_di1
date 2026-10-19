import type { Decimal, IsoDate, PnlPoint } from '@/api/contract';
import { addDays, formatDate } from '@/shared/format';

export interface ChartPoint {
  date: IsoDate;
  label: string;
  /** Plotting coordinate only; every figure shown as text is formatted from the string. */
  cumulative: number | null;
  /** The exact published value, for the tooltip. */
  cumulativeText: Decimal | null;
}

/**
 * One point per calendar day from the first published day in [start, end] to `end`. The line
 * is the backend's `range_cumulative_pnl`, the daily P&L summed from the chosen start (OQ-31
 * item 8): the browser only draws it. A day without that sum (no published day, or a missing
 * daily P&L from there on) is `null`, which breaks the line, so a gap is never bridged and
 * nothing is interpolated. Days before the first publication would all be gaps, so they are
 * left out: the work is bounded by the published history, however early `start` is.
 */
export function toChartData(items: PnlPoint[], start: IsoDate, end: IsoDate): ChartPoint[] {
  const byDate = new Map(items.map((item) => [item.date, item]));
  const published = items.map((item) => item.date).filter((date) => date >= start && date <= end);
  if (published.length === 0) return [];
  const first = published.reduce((a, b) => (b < a ? b : a));
  const points: ChartPoint[] = [];
  for (let date = first; date <= end; date = addDays(date, 1)) {
    const item = byDate.get(date);
    const value = item?.range_cumulative_pnl ?? null;
    points.push({
      date,
      label: formatDate(date).slice(0, 5),
      // A chart needs numbers. Converting for the pixel position only is formatting, not
      // calculation; the exact value stays in the string.
      cumulative: value === null ? null : Number(value),
      cumulativeText: value,
    });
  }
  return points;
}

export const hasHistory = (points: ChartPoint[]) => points.some((p) => p.cumulative !== null);
