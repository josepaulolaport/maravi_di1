import type { PnlPoint } from '@/api/contract';

import { hasIncompleteDay, incompleteReason, toChartData } from './chartData';

/** A processed point whose range sum is `range`. */
const point = (date: string, range: string, extra: Partial<PnlPoint> = {}): PnlPoint => ({
  date,
  daily_pnl: '10.00',
  range_cumulative_pnl: range,
  status: 'PROCESSED',
  ...extra,
});

/** A day that is not processed (OQ-41 item 2): only the range sum, carried flat. */
const unprocessed = (date: string, range: string): PnlPoint => ({
  date,
  daily_pnl: null,
  range_cumulative_pnl: range,
  status: 'NOT_PROCESSED',
});

describe('toChartData (§11.4, OQ-16, OQ-31, OQ-41)', () => {
  it('OQ-31 draws the range sum, never the since-inception cumulative', () => {
    const points = toChartData([point('2026-10-15', '-8034.1345282660')]);

    expect(points.map((p) => [p.cumulative, p.cumulativeText])).toEqual([
      [-8034.134528266, '-8034.1345282660'],
    ]);
  });

  it('OQ-41 draws every calendar day the API returns, with no gap and no trim', () => {
    const items = [
      unprocessed('2026-10-13', '0'),
      point('2026-10-14', '0'),
      point('2026-10-15', '-8034.1345282660'),
      point('2026-10-16', '-8034.1345282660', {
        status: 'PROCESSED_WITH_ISSUES',
        daily_pnl: null,
      }),
      unprocessed('2026-10-17', '-8034.1345282660'),
    ];

    const points = toChartData(items);

    expect(points.map((p) => [p.label, p.cumulative])).toEqual([
      ['13/10', 0],
      ['14/10', 0],
      ['15/10', -8034.134528266],
      ['16/10', -8034.134528266],
      ['17/10', -8034.134528266],
    ]);
  });

  it('OQ-41 item 5 gives the reason a day adds nothing: its status, or no daily P&L', () => {
    const points = toChartData([
      unprocessed('2026-10-13', '0'),
      point('2026-10-14', '0', { status: 'FAILED', daily_pnl: null }),
      point('2026-10-15', '0', { status: 'RUNNING', daily_pnl: null }),
      point('2026-10-16', '0', { daily_pnl: null }),
      point('2026-10-17', '10.00', { status: 'PROCESSED_WITH_ISSUES' }),
    ]);

    expect(points.map(incompleteReason)).toEqual([
      'Não processado',
      'Erro',
      'Processando',
      'P&L diário indisponível',
      null,
    ]);
  });

  it('OQ-41 item 5 reports whether any day of the range is not complete', () => {
    expect(hasIncompleteDay(toChartData([point('2026-10-14', '10.00')]))).toBe(false);
    expect(
      hasIncompleteDay(
        toChartData([point('2026-10-14', '10.00'), unprocessed('2026-10-15', '10.00')]),
      ),
    ).toBe(true);
  });

  it('§11.4 an empty range draws nothing', () => {
    expect(toChartData([])).toEqual([]);
  });
});
