import type { IsoDate, IsoDateTime } from '@/api/contract';
import { formatDate, formatQuantity, isIsoDate, UNAVAILABLE } from '@/shared/format';

// Formatting used only by Central de Controle. Dates and counts, never money.

const dateTime = new Intl.DateTimeFormat('pt-BR', {
  timeZone: 'America/Sao_Paulo',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** A job timestamp in Brasília time: 16/10/2026 18:35. */
export function formatDateTime(value: IsoDateTime | null | undefined): string {
  if (!value) return UNAVAILABLE;
  const parts = Object.fromEntries(
    dateTime.formatToParts(new Date(value)).map((part) => [part.type, part.value]),
  );
  return `${parts.day}/${parts.month}/${parts.year} ${parts.hour}:${parts.minute}`;
}

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
