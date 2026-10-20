import { formatQuantity } from '@/shared/format';

// Formatting used only by Central de Controle. Dates and counts, never money.

/** Days committed of the range: "2 / 5 dias" (OQ-23). */
export function formatProgress(done: number, total: number): string {
  return `${formatQuantity(done)} / ${formatQuantity(total)} ${total === 1 ? 'dia' : 'dias'}`;
}

/** The first block of the request's UUID, enough to tell jobs apart in the history. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}
