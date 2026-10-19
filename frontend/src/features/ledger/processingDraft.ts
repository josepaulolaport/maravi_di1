import type { IsoDate, OutdatedRange } from '@/api/contract';
import type { ProcessingDraft } from '@/shared/processing/ProcessingRequestModal';

// What the Lançamentos "Processar" buttons prefill (user, 2026-10-18; OQ-21 draft). The dates
// come from the backend (GET /processing/outdated); here they are only chosen, never computed.

const earliest = (dates: (IsoDate | null)[]) =>
  dates.filter((d): d is IsoDate => d !== null).sort()[0] ?? null;

/**
 * "Processar": from the first stale or unprocessed day of the chain(s) that are behind, to the
 * period's end. Caixa when only the cash is behind, Tudo otherwise (a trade affects both).
 * With nothing behind, the whole period, Tudo.
 */
export function processDraft(outdated: OutdatedRange | undefined, start: IsoDate, end: IsoDate) {
  const cash = outdated?.cash_from ?? null;
  const positions = outdated?.positions_from ?? null;
  const from = earliest([cash, positions]);
  const draft: ProcessingDraft =
    from === null
      ? { start, end, scope: 'ALL' }
      : { start: from, end, scope: positions === null ? 'CASH' : 'ALL' };
  return draft;
}

/** "Processar caixa": the cash chain only, from its first stale or unprocessed day. */
export function processCashDraft(
  outdated: OutdatedRange | undefined,
  start: IsoDate,
  end: IsoDate,
): ProcessingDraft {
  return { start: outdated?.cash_from ?? start, end, scope: 'CASH' };
}
