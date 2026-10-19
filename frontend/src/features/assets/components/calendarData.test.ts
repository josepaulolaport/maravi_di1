import type { ReferencePrice, ReferencePriceDay } from '@/api/contract';

import {
  calendarRows,
  CALENDAR_DAYS,
  calendarWindow,
  resolveRange,
  toPriceChart,
} from './calendarData';

function day(date: string, pu: string, rate: string | null): ReferencePriceDay {
  const preferred: ReferencePrice = {
    id: `p-${date}`,
    asset_id: 'a',
    reference_date: date,
    source: 'MANUAL',
    input_kind: 'PU',
    pu,
    rate,
    revision: 1,
    created_at: `${date}T18:00:00-03:00`,
    superseded_at: null,
  };
  return { reference_date: date, preferred, current: [preferred] };
}

describe('calendarWindow', () => {
  it('§11.2 ends today while the contract is alive: 30 calendar days', () => {
    expect(CALENDAR_DAYS).toBe(30);
    expect(calendarWindow('2026-10-18', '2028-01-03')).toEqual({
      start: '2026-09-19',
      end: '2026-10-18',
    });
  });

  it('§7.4 ends on the maturity date once it has passed (OQ-1)', () => {
    expect(calendarWindow('2026-10-18', '2026-10-05')).toEqual({
      start: '2026-09-06',
      end: '2026-10-05',
    });
  });

  it('§11.2 ends today when the contract has no maturity', () => {
    expect(calendarWindow('2026-10-18', null).end).toBe('2026-10-18');
  });
});

describe('resolveRange', () => {
  const today = '2026-10-18';
  const maturity = '2028-01-03';

  it('§11.2 defaults to the last 30 days up to min(today, maturity)', () => {
    expect(resolveRange({}, today, maturity)).toEqual({ start: '2026-09-19', end: '2026-10-18' });
  });

  it('§11.2 uses the inclusive range from the URL', () => {
    expect(resolveRange({ start: '2026-10-01', end: '2026-10-05' }, today, maturity)).toEqual({
      start: '2026-10-01',
      end: '2026-10-05',
    });
  });

  it('OQ-14 OQ-1 clamps the end to today, or to the maturity date once it has passed', () => {
    expect(resolveRange({ start: '2026-10-01', end: '2026-10-25' }, today, maturity).end).toBe(
      '2026-10-18',
    );
    expect(resolveRange({ start: '2026-09-01', end: '2026-10-18' }, today, '2026-10-01')).toEqual({
      start: '2026-09-01',
      end: '2026-10-01',
    });
  });

  it('§11.2 ignores an invalid or reversed range', () => {
    expect(resolveRange({ start: '2026-10-05', end: '2026-10-01' }, today, maturity)).toEqual({
      start: '2026-09-19',
      end: '2026-10-18',
    });
    expect(resolveRange({ start: 'x', end: '2026-10-01' }, today, maturity).end).toBe('2026-10-18');
  });

  it('§11.1 without a range, a "registrar" date makes the default window end on it', () => {
    expect(resolveRange({ register: '2026-08-20' }, today, maturity)).toEqual({
      start: '2026-07-22',
      end: '2026-08-20',
    });
    // A future "registrar" date keeps the default window (the API rejects it on save).
    expect(resolveRange({ register: '2026-10-19' }, today, maturity).end).toBe('2026-10-18');
  });
});

describe('calendarRows', () => {
  it('§5 has one row per calendar day, newest first; a day without observation is null', () => {
    const rows = calendarRows([day('2026-10-16', '89250.31', '0.098')], '2026-10-15', '2026-10-17');

    expect(rows.map((r) => r.date)).toEqual(['2026-10-17', '2026-10-16', '2026-10-15']);
    expect(rows[0]?.day).toBeNull();
    expect(rows[1]?.day?.preferred.pu).toBe('89250.31');
    // No carry-forward: 17/10 does not inherit 16/10's price.
    expect(rows[2]?.day).toBeNull();
  });
});

describe('toPriceChart', () => {
  it('§11.2 plots only real observations, oldest first, with null gaps (never bridged)', () => {
    const items = [day('2026-10-16', '89250.31', '0.098'), day('2026-10-14', '89006.46', '0.10')];

    const points = toPriceChart(items, '2026-10-14', '2026-10-17', 'PU');

    expect(points.map((p) => p.label)).toEqual(['14/10', '15/10', '16/10', '17/10']);
    expect(points.map((p) => p.value)).toEqual([89006.46, null, 89250.31, null]);
    expect(points.map((p) => p.text)).toEqual(['89006.46', null, '89250.31', null]);
  });

  it('§11.2 plots the rate, and a missing rate is a gap', () => {
    const items = [day('2026-10-16', '89250.31', '0.098'), day('2026-10-15', '100000', null)];

    const points = toPriceChart(items, '2026-10-15', '2026-10-16', 'RATE');

    expect(points.map((p) => p.value)).toEqual([null, 0.098]);
    expect(points.map((p) => p.text)).toEqual([null, '0.098']);
  });
});
