import type { Decimal, IsoDate, IsoTime, LedgerEntry as ApiLedgerEntry } from '@/api/contract';

// One table row of Lançamentos (§11.3), mapped from a GET /ledger/entries row. The backend
// filters and orders the rows and signs every cash effect (P18); nothing is merged, sorted or
// calculated here. Instrument type and entry type are kept apart.

export type EntryType = 'BUY' | 'SELL' | 'DEPOSIT' | 'WITHDRAWAL';

export const ENTRY_TYPE_LABELS: Record<EntryType, string> = {
  BUY: 'Compra',
  SELL: 'Venda',
  DEPOSIT: 'Aporte',
  WITHDRAWAL: 'Retirada',
};

interface BaseEntry {
  /** Unique across both kinds: `trade:<id>` or `cash:<id>`. */
  key: string;
  id: string;
  date: IsoDate;
  entryType: EntryType;
  /** The backend's signed cash effect (`cash_amount`). */
  signedAmount: Decimal;
}

export interface TradeEntry extends BaseEntry {
  kind: 'trade';
  time: IsoTime;
  seq: number;
  instrumentTypeCode: string;
  assetCode: string;
  signedQuantity: number;
  pu: Decimal;
  rate: Decimal;
}

export interface CashEntry extends BaseEntry {
  kind: 'cash';
  createdAt: string;
}

export type LedgerEntry = TradeEntry | CashEntry;

export type SortDirection = 'asc' | 'desc';

export function toRow(entry: ApiLedgerEntry): LedgerEntry {
  if (entry.kind === 'TRADE') {
    return {
      kind: 'trade',
      key: `trade:${entry.id}`,
      id: entry.id,
      date: entry.date,
      time: entry.time,
      seq: entry.seq,
      entryType: entry.signed_quantity > 0 ? 'BUY' : 'SELL',
      instrumentTypeCode: entry.instrument_type_code,
      assetCode: entry.asset_code,
      signedQuantity: entry.signed_quantity,
      pu: entry.execution_pu,
      rate: entry.execution_rate,
      signedAmount: entry.cash_amount,
    };
  }
  return {
    kind: 'cash',
    key: `cash:${entry.id}`,
    id: entry.id,
    date: entry.date,
    entryType: entry.movement_type === 'DEPOSIT' ? 'DEPOSIT' : 'WITHDRAWAL',
    signedAmount: entry.cash_amount,
    createdAt: entry.created_at,
  };
}
