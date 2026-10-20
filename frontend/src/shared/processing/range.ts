import type { IsoDate } from '@/api/contract';

/** A complete range with A ≤ B; dates are ISO strings, so they compare as text. */
export function isValidRange(start: IsoDate | null, end: IsoDate | null): boolean {
  return start !== null && end !== null && start <= end;
}
