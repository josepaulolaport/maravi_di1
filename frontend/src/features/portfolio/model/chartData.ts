import type { DateStatus, Decimal, IsoDate, PnlPoint } from '@/api/contract';
import { formatDate, plotCoordinate } from '@/shared/format';
import { DATE_STATUS } from '@/shared/ui/dateStatus';

export interface ChartPoint {
  date: IsoDate;
  label: string;
  /** Plotting coordinate only; every figure shown as text is formatted from the string. */
  cumulative: number;
  /** The exact published value, for the tooltip. */
  cumulativeText: Decimal;
  /** The day's positions status (OQ-41 item 4). */
  status: DateStatus;
  /** The day's own daily P&L; null when it is not available. */
  daily: Decimal | null;
}

/**
 * One point per calendar day, as the API returns them (OQ-41 item 2). The line is the
 * backend's `range_cumulative_pnl`, the daily P&L summed from the chosen start (OQ-31 item 8),
 * which is never null: a day that is not complete adds 0 there, so the line never breaks. The
 * browser only draws it: nothing is summed, filtered or interpolated here.
 */
export function toChartData(items: PnlPoint[]): ChartPoint[] {
  return items.map((item) => ({
    date: item.date,
    label: formatDate(item.date).slice(0, 5),
    cumulative: plotCoordinate(item.range_cumulative_pnl),
    cumulativeText: item.range_cumulative_pnl,
    status: item.status,
    daily: item.daily_pnl,
  }));
}

/**
 * Why a day adds nothing to the line (OQ-41 item 5): its status when it is not processed
 * ("Não processado", "Erro", "Processando"), or "P&L diário indisponível" for a processed day
 * whose daily P&L is null. Null for a complete day.
 */
export function incompleteReason(point: ChartPoint): string | null {
  const processed = point.status === 'PROCESSED' || point.status === 'PROCESSED_WITH_ISSUES';
  if (!processed) return DATE_STATUS[point.status].label;
  return point.daily === null ? 'P&L diário indisponível' : null;
}

/** Whether any day of the range adds 0 because it is not complete (OQ-41 item 5). */
export const hasIncompleteDay = (points: ChartPoint[]) =>
  points.some((point) => incompleteReason(point) !== null);
