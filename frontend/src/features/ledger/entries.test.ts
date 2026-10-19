import { cashEntries, tradeEntries } from '@/api/mocks/fixtures';

import { toRow } from './entries';

// Fixture entries (src/api/mocks/fixtures.ts): trades 14/10 compra, 15/10 compra, 16/10 venda;
// aporte 14/10, retirada 16/10. The order of the rows is the backend's (GET /ledger/entries);
// the screen only maps each row for the table.

const [buy, , sell] = tradeEntries as [
  (typeof tradeEntries)[0],
  (typeof tradeEntries)[0],
  (typeof tradeEntries)[0],
];
const [deposit, withdrawal] = cashEntries as [(typeof cashEntries)[0], (typeof cashEntries)[0]];

describe('Lançamentos rows (§11.3)', () => {
  it('§11.3 maps a trade to Compra or Venda by the sign of its quantity', () => {
    expect(toRow(buy).entryType).toBe('BUY');
    expect(toRow(sell).entryType).toBe('SELL');
  });

  it('§6.2 maps a cash entry to Aporte or Retirada by the sign of its amount', () => {
    expect(toRow(deposit).entryType).toBe('DEPOSIT');
    expect(toRow(withdrawal).entryType).toBe('WITHDRAWAL');
  });

  it('§6 every entry, trade or cash, carries its id, date and time', () => {
    expect(toRow(buy)).toMatchObject({ id: buy.id, date: '2026-10-14', time: '14:10:00' });
    expect(toRow(withdrawal)).toMatchObject({
      id: withdrawal.id,
      date: '2026-10-16',
      time: '17:30:00',
    });
  });

  it('§11.3 shows the signed cash effect exactly as the backend sends it', () => {
    expect(toRow(sell).signedAmount).toBe('356408.8906133732');
    expect(toRow(withdrawal).signedAmount).toBe('-50000.00');
  });
});
