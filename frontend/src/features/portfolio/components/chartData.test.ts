import type { PnlPoint } from '@/api/contract';

import { hasHistory, toChartData } from './chartData';

/** A published point whose range sum is `range`; its daily and since-inception figures differ. */
const point = (date: string, range: string | null, extra: Partial<PnlPoint> = {}): PnlPoint => ({
  date,
  daily_pnl: range,
  cumulative_pnl: '999999.99',
  range_cumulative_pnl: range,
  pnl_status: range === null ? 'MISSING' : 'COMPLETE',
  status: 'PROCESSED',
  published_at: '2026-10-16T18:40:00-03:00',
  ...extra,
});

describe('toChartData (§11.4, OQ-16, OQ-31)', () => {
  it('OQ-31 draws the range sum, never the since-inception cumulative', () => {
    const points = toChartData(
      [point('2026-10-15', '-8034.1345282660')],
      '2026-10-15',
      '2026-10-15',
    );

    expect(points.map((p) => [p.cumulative, p.cumulativeText])).toEqual([
      [-8034.134528266, '-8034.1345282660'],
    ]);
  });

  it('draws every day with a range sum and leaves every other calendar day as a gap', () => {
    const items = [
      point('2026-10-14', '0'),
      point('2026-10-15', '-8034.1345282660'),
      point('2026-10-16', null),
      point('2026-10-17', null, { daily_pnl: '500.00' }),
    ];

    const points = toChartData(items, '2026-10-13', '2026-10-18');

    // 13/10 comes before the first published day, so the chart starts on 14/10.
    expect(points.map((p) => [p.label, p.cumulative])).toEqual([
      ['14/10', 0],
      ['15/10', -8034.134528266],
      ['16/10', null], // incomplete
      ['17/10', null], // after the first gap the range sum stays unavailable
      ['18/10', null], // not published
    ]);
  });

  it('OQ-23 draws a complete day whose positions read Processado com pendências', () => {
    const points = toChartData(
      [point('2026-10-14', '0', { status: 'PROCESSED_WITH_ISSUES' })],
      '2026-10-14',
      '2026-10-14',
    );

    expect(points.map((p) => p.cumulative)).toEqual([0]);
  });

  it('§11.4 starts at the first published day, so a very early start costs nothing', () => {
    const items = [point('2026-10-14', '0'), point('2026-10-15', '-8034.1345282660')];

    const points = toChartData(items, '0001-01-01', '2026-10-16');

    expect(points.map((p) => [p.label, p.cumulative])).toEqual([
      ['14/10', 0],
      ['15/10', -8034.134528266],
      ['16/10', null], // not published
    ]);
  });

  it('§11.4 draws nothing when nothing in the range was published', () => {
    expect(toChartData([], '0001-01-01', '2026-10-16')).toEqual([]);
  });

  it('reports when there is no complete history to draw', () => {
    expect(hasHistory(toChartData([point('2026-10-16', null)], '2026-10-16', '2026-10-16'))).toBe(
      false,
    );
    expect(hasHistory(toChartData([point('2026-10-14', '0')], '2026-10-14', '2026-10-14'))).toBe(
      true,
    );
  });
});
