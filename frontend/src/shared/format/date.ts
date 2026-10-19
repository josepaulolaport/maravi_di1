import type { IsoDate, IsoTime } from '@/api/contract';

import { UNAVAILABLE } from './number';

// Calendar dates travel as `YYYY-MM-DD` and are shown as DD/MM/YYYY. They are formatted by
// splitting the string, never through `Date`, so no time zone can shift a day.

/** 2026-10-15 → 15/10/2026 */
export function formatDate(value: IsoDate | null | undefined): string {
  if (!value) return UNAVAILABLE;
  const [year, month, day] = value.split('-');
  return `${day ?? ''}/${month ?? ''}/${year ?? ''}`;
}

/** 14:10:00 → 14:10 */
export function formatTime(value: IsoTime | null | undefined): string {
  return value ? value.slice(0, 5) : UNAVAILABLE;
}

const DAY_MS = 86_400_000;

/** Today's calendar date in São Paulo, where the business day is defined (OQ-14). */
export function todayInSaoPaulo(now: Date = new Date()): IsoDate {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}

/** Calendar arithmetic on ISO dates (UTC-based, so DST never applies). */
export function addDays(value: IsoDate, amount: number): IsoDate {
  return new Date(Date.parse(`${value}T00:00:00Z`) + amount * DAY_MS).toISOString().slice(0, 10);
}

export function isIsoDate(value: string | null | undefined): value is IsoDate {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return !Number.isNaN(time) && new Date(time).toISOString().startsWith(value);
}

/** The inclusive range [A, B] (OQ-11): 14/10/2026 a 16/10/2026. */
export function formatPeriod(start: IsoDate, end: IsoDate): string {
  return `${formatDate(start)} a ${formatDate(end)}`;
}

/** A typed DD/MM/AAAA date → YYYY-MM-DD; `null` for anything else. */
export function parsePtBrDate(text: string): IsoDate | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text.trim());
  if (!match) return null;
  const [, day, month, year] = match;
  const iso = `${year ?? ''}-${month ?? ''}-${day ?? ''}`;
  return isIsoDate(iso) ? iso : null;
}
