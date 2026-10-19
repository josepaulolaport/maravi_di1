import type { IsoDate } from '@/api/contract';
import { formatDate, formatQuantity, isIsoDate } from '@/shared/format';

// Formatting used only by Central de Controle. Dates and counts, never money.

/** The inclusive requested range [A, B] (OQ-11): 14/10/2026 a 16/10/2026. */
export function formatPeriod(start: IsoDate, end: IsoDate): string {
  return `${formatDate(start)} a ${formatDate(end)}`;
}

/** A count of days in pt-BR: 1.000. */
export function formatDays(days: number): string {
  return formatQuantity(days);
}

/** Days staged so far: "2 / 5 dias". */
export function formatProgress(done: number, total: number): string {
  return `${formatDays(done)} / ${formatDays(total)} ${total === 1 ? 'dia' : 'dias'}`;
}

/** The first block of the request's UUID, enough to tell jobs apart in the history. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

/** A typed DD/MM/AAAA date → YYYY-MM-DD; `null` for anything else. */
export function parseDateInput(text: string): IsoDate | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text.trim());
  if (!match) return null;
  const [, day, month, year] = match;
  const iso = `${year ?? ''}-${month ?? ''}-${day ?? ''}`;
  return isIsoDate(iso) ? iso : null;
}
