import type { Decimal, IsoDate, IsoDateTime, ReferencePriceDay } from '@/api/contract';
import { addDays, formatDate, isIsoDate } from '@/shared/format';

/** Calendar days shown on the contract page, ending on min(today, maturity) (§11.2). */
export const CALENDAR_DAYS = 30;

/**
 * The calendar's window: the last 30 calendar days up to today, or up to the maturity date
 * once it has passed (no price exists or is accepted after it, OQ-1).
 */
export function calendarWindow(
  today: IsoDate,
  maturity: IsoDate | null,
): { start: IsoDate; end: IsoDate } {
  const end = maturity !== null && maturity < today ? maturity : today;
  return { start: addDays(end, -(CALENDAR_DAYS - 1)), end };
}

/**
 * The calendar's period (§11.2): the inclusive range from the URL (`?inicio=&fim=`), its end
 * clamped to min(today, maturity); otherwise the last 30 days, ending on the "registrar" date
 * when one is given (a Pendência for an older date opens the calendar on it).
 */
export function resolveRange(
  requested: { start?: string | null; end?: string | null; register?: string | null },
  today: IsoDate,
  maturity: IsoDate | null,
): { start: IsoDate; end: IsoDate } {
  const fallback = calendarWindow(today, maturity);
  const { start, end, register } = requested;
  if (isIsoDate(start) && isIsoDate(end) && start <= end) {
    const clampedEnd = end < fallback.end ? end : fallback.end;
    return { start: start < clampedEnd ? start : clampedEnd, end: clampedEnd };
  }
  if (isIsoDate(register) && register < fallback.end) {
    return calendarWindow(register, maturity);
  }
  return fallback;
}

export interface CalendarRow {
  date: IsoDate;
  /** The day's observations, or `null`: no observation on that exact date (§5). */
  day: ReferencePriceDay | null;
}

/** One row per calendar day of [start, end], newest first. Nothing is carried forward (§5). */
export function calendarRows(
  items: ReferencePriceDay[],
  start: IsoDate,
  end: IsoDate,
): CalendarRow[] {
  const byDate = new Map(items.map((item) => [item.reference_date, item]));
  const rows: CalendarRow[] = [];
  for (let date = end; date >= start; date = addDays(date, -1)) {
    rows.push({ date, day: byDate.get(date) ?? null });
  }
  return rows;
}

export type ChartMode = 'PU' | 'RATE';

export interface PricePoint {
  date: IsoDate;
  label: string;
  /** Plotting coordinate only; every figure shown as text is formatted from `text`. */
  value: number | null;
  /** The exact decimal string of the preferred observation. */
  text: Decimal | null;
}

/**
 * One point per calendar day of [start, end], oldest first. Only real observations are drawn;
 * any other day is `null`, which breaks the line, so a gap is never bridged (§11.2).
 */
export function toPriceChart(
  items: ReferencePriceDay[],
  start: IsoDate,
  end: IsoDate,
  mode: ChartMode,
): PricePoint[] {
  const byDate = new Map(items.map((item) => [item.reference_date, item]));
  const points: PricePoint[] = [];
  for (let date = start; date <= end; date = addDays(date, 1)) {
    const preferred = byDate.get(date)?.preferred;
    const text = (mode === 'PU' ? preferred?.pu : preferred?.rate) ?? null;
    points.push({
      date,
      label: formatDate(date).slice(0, 5),
      // A chart needs numbers: converting for the pixel position only is formatting, not
      // calculation; the exact value stays in `text`.
      value: text === null ? null : Number(text),
      text,
    });
  }
  return points;
}

const dateTimeParts = new Intl.DateTimeFormat('pt-BR', {
  timeZone: 'America/Sao_Paulo',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** An instant shown in São Paulo time: 2026-10-17T10:00:00-03:00 → 17/10/2026 10:00. */
export function formatDateTime(value: IsoDateTime): string {
  const parts = Object.fromEntries(
    dateTimeParts.formatToParts(new Date(value)).map((part) => [part.type, part.value]),
  );
  return `${parts.day ?? ''}/${parts.month ?? ''}/${parts.year ?? ''} ${parts.hour ?? ''}:${parts.minute ?? ''}`;
}
