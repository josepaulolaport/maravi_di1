import { cashMovements, trades } from '@/api/mocks/fixtures';

import { mergeEntries, sortEntries } from './entries';

// Fixture entries (src/api/mocks/fixtures.ts): trades seq 1 (14/10 14:10), 2 (15/10 10:30),
// 3 (16/10 15:00); aporte 14/10, retirada 16/10.

const keys = (entries: ReturnType<typeof mergeEntries>) => entries.map((e) => e.key);

describe('Lançamentos entries (§11.3)', () => {
  it('§11.3 merges trades and cash movements, newest date first, trades before cash in a date', () => {
    const merged = sortEntries(mergeEntries(trades, cashMovements), 'desc');

    expect(keys(merged)).toEqual([
      `trade:${trades[2]?.id ?? ''}`,
      `cash:${cashMovements[1]?.id ?? ''}`,
      `trade:${trades[1]?.id ?? ''}`,
      `trade:${trades[0]?.id ?? ''}`,
      `cash:${cashMovements[0]?.id ?? ''}`,
    ]);
  });

  it('§6.1 orders trades of one date by time, then seq, descending', () => {
    const base = trades[0];
    if (!base) throw new Error('fixture');
    const sameDate = [
      { ...base, id: 'a', trade_time: '10:00:00', seq: 7 },
      { ...base, id: 'b', trade_time: '11:00:00', seq: 5 },
      { ...base, id: 'c', trade_time: '10:00:00', seq: 9 },
    ];

    const merged = sortEntries(mergeEntries(sameDate, []), 'desc');

    expect(keys(merged)).toEqual(['trade:b', 'trade:c', 'trade:a']);
  });

  it('§11.3 ascending order is the exact reverse of the default order', () => {
    const merged = mergeEntries(trades, cashMovements);

    expect(keys(sortEntries(merged, 'asc'))).toEqual(keys(sortEntries(merged, 'desc')).reverse());
  });

  it('§11.3 maps a trade to Compra or Venda by the sign of its quantity', () => {
    const merged = mergeEntries(trades, cashMovements);

    expect(merged.find((e) => e.key === `trade:${trades[0]?.id ?? ''}`)?.entryType).toBe('BUY');
    expect(merged.find((e) => e.key === `trade:${trades[2]?.id ?? ''}`)?.entryType).toBe('SELL');
    expect(merged.find((e) => e.key === `cash:${cashMovements[0]?.id ?? ''}`)?.entryType).toBe(
      'DEPOSIT',
    );
    expect(merged.find((e) => e.key === `cash:${cashMovements[1]?.id ?? ''}`)?.entryType).toBe(
      'WITHDRAWAL',
    );
  });

  it('§11.3 shows a cash movement amount with the sign of its direction, as given', () => {
    const merged = mergeEntries([], cashMovements);

    expect(merged.map((e) => e.signedAmount)).toEqual(['1500000.00', '-50000.00']);
  });

  it('§11.3 uses the backend cash_amount for a trade', () => {
    const merged = mergeEntries(trades, []);

    expect(merged.map((e) => e.signedAmount)).toEqual([
      '-890064.6254673500',
      '-410285.00',
      '356408.8906133732',
    ]);
  });
});
