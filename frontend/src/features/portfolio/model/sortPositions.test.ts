import type { PositionRow } from '@/api/contract';

import { sortPositions } from './sortPositions';

function row(assetCode: string, patch: Partial<PositionRow> = {}): PositionRow {
  return {
    asset_id: assetCode,
    asset_code: assetCode,
    maturity_date: '2028-01-04',
    quantity: 1,
    average_entry_pu: '100.00',
    average_entry_rate: '0.100000000000',
    reference_source: 'MANUAL',
    reference_pu: '100.00',
    reference_rate: '0.100000000000',
    reference_price_changed: false,
    financial_total: '100.00',
    position_pnl: '0.00',
    trades_pnl: '0.00',
    daily_pnl: '0.00',
    valuation_status: 'COMPLETE',
    pnl_status: 'COMPLETE',
    ...patch,
  };
}

const codes = (rows: PositionRow[]) => rows.map((item) => item.asset_code);

describe('sortPositions (§11.4)', () => {
  it('§11.4 orders a decimal column by value, with null last in either direction', () => {
    const rows = [
      row('B', { financial_total: null }),
      row('A', { financial_total: '10.00' }),
      row('C', { financial_total: '9.00' }),
    ];

    expect(codes(sortPositions(rows, { key: 'financial_total', direction: 'asc' }))).toEqual([
      'C',
      'A',
      'B',
    ]);
    expect(codes(sortPositions(rows, { key: 'financial_total', direction: 'desc' }))).toEqual([
      'A',
      'C',
      'B',
    ]);
  });

  it('§11.4 breaks a tie by asset code, ascending, even when the column is descending', () => {
    const rows = [
      row('DI1F29', { financial_total: '10.00' }),
      row('DI1F28', { financial_total: '10.00' }),
    ];

    expect(codes(sortPositions(rows, { key: 'financial_total', direction: 'desc' }))).toEqual([
      'DI1F28',
      'DI1F29',
    ]);
  });

  it('§11.4 sorts quantity as a number', () => {
    const rows = [row('B', { quantity: 10 }), row('A', { quantity: 2 })];

    expect(codes(sortPositions(rows, { key: 'quantity', direction: 'asc' }))).toEqual(['A', 'B']);
  });
});
