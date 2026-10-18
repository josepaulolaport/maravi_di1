import type { CashMovement, Trade } from '@/api/contract';
import { cashMovements, trades } from '@/api/mocks/fixtures';
import { cashEntry, tradeEntry } from '@/api/mocks/handlers/ledger';

import { toRow } from './entries';

// Fixture entries (src/api/mocks/fixtures.ts): trades seq 1 (14/10 compra), 2 (15/10 compra),
// 3 (16/10 venda); aporte 14/10, retirada 16/10. The order of the rows is the backend's
// (GET /ledger/entries); the screen only maps each row for the table.

const [buy, , sell] = trades as [Trade, Trade, Trade];
const [deposit, withdrawal] = cashMovements as [CashMovement, CashMovement];

describe('Lançamentos rows (§11.3)', () => {
  it('§11.3 maps a trade to Compra or Venda by the sign of its quantity', () => {
    expect(toRow(tradeEntry(buy)).entryType).toBe('BUY');
    expect(toRow(tradeEntry(sell)).entryType).toBe('SELL');
  });

  it('§6.2 maps a cash movement to Aporte or Retirada by its type', () => {
    expect(toRow(cashEntry(deposit)).entryType).toBe('DEPOSIT');
    expect(toRow(cashEntry(withdrawal)).entryType).toBe('WITHDRAWAL');
  });

  it('§11.3 keys each row by its kind, so a trade and a movement never collide', () => {
    expect(toRow(tradeEntry(buy)).key).toBe(`trade:${buy.id}`);
    expect(toRow(cashEntry(deposit)).key).toBe(`cash:${deposit.id}`);
  });

  it('§11.3 shows the signed cash effect exactly as the backend sends it', () => {
    expect(toRow(tradeEntry(sell)).signedAmount).toBe('356408.8906133732');
    expect(toRow(cashEntry(withdrawal)).signedAmount).toBe('-50000.00');
  });
});
