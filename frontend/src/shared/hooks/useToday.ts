import type { IsoDate } from '@/api/contract';
import { todayInSaoPaulo } from '@/shared/format';

/** Today's calendar date in São Paulo, where the business day is defined (OQ-14). */
export function useToday(): IsoDate {
  return todayInSaoPaulo();
}
