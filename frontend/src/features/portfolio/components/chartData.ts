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
 * One point per calendar day of [start, end]. A day is drawn only when its cumulative P&L is
 * published, complete and not stale (§11.4, OQ-16); any other day is `null`, which breaks the
 * line, so a gap is never bridged and nothing is interpolated.
 */
export function toChartData(items: PnlPoint[], start: IsoDate, end: IsoDate): ChartPoint[] {
  const byDate = new Map(items.map((item) => [item.date, item]));
  const points: ChartPoint[] = [];
  for (let date = start; date <= end; date = addDays(date, 1)) {
    const item = byDate.get(date);
    const valid =
      item !== undefined &&
      item.pnl_status === 'COMPLETE' &&
      item.status === 'FRESH' &&
      item.cumulative_pnl !== null;
    points.push({
      date,
      label: formatDate(date).slice(0, 5),
      // A chart needs numbers. Converting for the pixel position only is formatting, not
      // calculation; the exact value stays in the string.
      cumulative: valid ? Number(item.cumulative_pnl) : null,
      cumulativeText: valid ? item.cumulative_pnl : null,
    });
  }
  return points;
}

export const hasHistory = (points: ChartPoint[]) => points.some((p) => p.cumulative !== null);
