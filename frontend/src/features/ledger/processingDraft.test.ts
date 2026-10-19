import type { OutdatedRange } from '@/api/contract';

import { processCashDraft, processDraft } from './processingDraft';

// The Lançamentos "Processar" prefill rule (user, 2026-10-18; OQ-21 draft): from the first day
// of the chain(s) behind to the period's end; Caixa when only the cash is behind, Tudo
// otherwise; with nothing behind, the whole period, Tudo.

const outdated = (cash: string | null, positions: string | null): OutdatedRange => ({
  start_date: '2026-10-01',
  end_date: '2026-10-16',
  cash_from: cash,
  positions_from: positions,
});

describe('Processar prefill (OQ-21)', () => {
  it('§10.1 only the cash behind: Caixa from its first day', () => {
    expect(processDraft(outdated('2026-10-15', null), '2026-10-01', '2026-10-16')).toEqual({
      start: '2026-10-15',
      end: '2026-10-16',
      scope: 'CASH',
    });
  });

  it('§10.1 only the positions behind: Tudo from their first day', () => {
    expect(processDraft(outdated(null, '2026-10-16'), '2026-10-01', '2026-10-16')).toEqual({
      start: '2026-10-16',
      end: '2026-10-16',
      scope: 'ALL',
    });
  });

  it('§10.1 both behind from different days: Tudo from the earliest', () => {
    expect(
      processDraft(outdated('2026-10-15', '2026-10-16'), '2026-10-01', '2026-10-16'),
    ).toMatchObject({ start: '2026-10-15', scope: 'ALL' });
    expect(
      processDraft(outdated('2026-10-16', '2026-10-14'), '2026-10-01', '2026-10-16'),
    ).toMatchObject({ start: '2026-10-14', scope: 'ALL' });
  });

  it('§10.1 nothing behind: the whole period, Tudo', () => {
    expect(processDraft(outdated(null, null), '2026-10-01', '2026-10-16')).toEqual({
      start: '2026-10-01',
      end: '2026-10-16',
      scope: 'ALL',
    });
  });

  it('§10.1 "Processar caixa": Caixa from the cash chain\'s first day behind', () => {
    expect(
      processCashDraft(outdated('2026-10-15', '2026-10-14'), '2026-10-01', '2026-10-16'),
    ).toEqual({ start: '2026-10-15', end: '2026-10-16', scope: 'CASH' });
  });
});
