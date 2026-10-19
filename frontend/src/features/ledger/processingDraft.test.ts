import { processCashDraft, processDraft } from './processingDraft';

// The Lançamentos "Processar" prefills (user, 2026-10-18; OQ-21, P19 dropped): the whole
// period with Tudo; "Processar caixa" from the first of Caixa D−1 / D0 that is behind.

describe('Processar prefill (OQ-21)', () => {
  it('§10.1 "Processar": the whole period, Tudo', () => {
    expect(processDraft('2026-10-01', '2026-10-16')).toEqual({
      start: '2026-10-01',
      end: '2026-10-16',
      scope: 'ALL',
    });
  });

  it('§11.3 "Processar caixa": Caixa from the given day to the period end', () => {
    expect(processCashDraft('2026-10-15', '2026-10-16')).toEqual({
      start: '2026-10-15',
      end: '2026-10-16',
      scope: 'CASH',
    });
  });
});
