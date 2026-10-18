import type { PnlPoint } from '@/api/contract';

import { hasHistory, toChartData } from './chartData';

const point = (
  date: string,
  cumulative: string | null,
  extra: Partial<PnlPoint> = {},
): PnlPoint => ({
  date,
  daily_pnl: cumulative,
  cumulative_pnl: cumulative,
  pnl_status: cumulative === null ? 'MISSING' : 'COMPLETE',
  stale: false,
  ...extra,
});

describe('toChartData (§11.4, OQ-16)', () => {
  it('draws only complete, current days and leaves every other calendar day as a gap', () => {
    const items = [
      point('2026-10-14', '0'),
      point('2026-10-15', '-8034.1345282660'),
      point('2026-10-16', null),
      point('2026-10-17', '500.00', { stale: true }),
    ];

    const points = toChartData(items, '2026-10-13', '2026-10-18');

    expect(points[2]?.cumulativeText).toBe('-8034.1345282660');
    expect(points.map((p) => [p.label, p.cumulative])).toEqual([
      ['13/10', null], // not published
      ['14/10', 0],
      ['15/10', -8034.134528266],
      ['16/10', null], // incomplete
      ['17/10', null], // stale
      ['18/10', null], // not published
    ]);
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
