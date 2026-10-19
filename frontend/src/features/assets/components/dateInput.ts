import type { IsoDate } from '@/api/contract';
import { isIsoDate } from '@/shared/format';

/**
 * `DateInput` parser for a typed pt-BR date: "02/01/2031" → "2031-01-02"; `null` when the text
 * is not a real DD/MM/AAAA date. String manipulation only, so no time zone can shift the day.
 */
export function parsePtBrDate(text: string): IsoDate | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text.trim());
  if (!match) return null;
  const [, day = '', month = '', year = ''] = match;
  const iso = `${year}-${month}-${day}`;
  return isIsoDate(iso) ? iso : null;
}
