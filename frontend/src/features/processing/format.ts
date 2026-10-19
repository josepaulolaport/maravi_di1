import { formatDays } from '@/shared/format';

export { formatDays, formatPeriod, parsePtBrDate as parseDateInput } from '@/shared/format';

// Formatting used only by Central de Controle. Dates and counts, never money.

/** Days staged so far: "2 / 5 dias". */
export function formatProgress(done: number, total: number): string {
  return `${formatDays(done)} / ${formatDays(total)} ${total === 1 ? 'dia' : 'dias'}`;
}

/** The first block of the request's UUID, enough to tell jobs apart in the history. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}
