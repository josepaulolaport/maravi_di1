import type { IsoTime } from '@/api/contract';

/** The current São Paulo time as `HH:MM`, the form's suggestion for a trade (OQ-13). */
export function nowInSaoPaulo(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/Sao_Paulo',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(now);
}

/** `HH:MM` from the time input → the API's `HH:MM:SS`. */
export const toIsoTime = (value: string): IsoTime => (value.length === 5 ? `${value}:00` : value);
