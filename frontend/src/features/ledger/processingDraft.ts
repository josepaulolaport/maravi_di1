import type { IsoDate } from '@/api/contract';
import type { ProcessingDraft } from '@/shared/processing/ProcessingRequestModal';

// What the Lançamentos "Processar" buttons prefill (user, 2026-10-18; OQ-21). The user
// dropped GET /processing/outdated (P19), so nothing here asks which days are behind: the
// dates are the period's, or the strip's own D−1 / D0.

/** "Processar": the whole period, Tudo; the user narrows it before confirming. */
export const processDraft = (start: IsoDate, end: IsoDate): ProcessingDraft => ({
  start,
  end,
  scope: 'ALL',
});

/** "Processar caixa": the cash chain from `from` (Caixa D−1 or D0, the first behind). */
export const processCashDraft = (from: IsoDate, end: IsoDate): ProcessingDraft => ({
  start: from,
  end,
  scope: 'CASH',
});
