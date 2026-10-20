import type { Decimal, IsoDate, IsoTime, LedgerEntry as ApiLedgerEntry } from '@/api/contract';
import {
  formatDate,
  formatPu,
  formatSignedMoney,
  formatSignedQuantity,
  formatTime,
} from '@/shared/format';

// One table row of Lançamentos (§11.3), mapped from a GET /ledger/entries row. The backend
// filters and orders the rows and signs every cash effect (P18); nothing is merged, sorted or
// calculated here. Instrument type and entry type are kept apart.

type EntryType = 'BUY' | 'SELL' | 'DEPOSIT' | 'WITHDRAWAL';

export const ENTRY_TYPE_LABELS: Record<EntryType, string> = {
  BUY: 'Compra',
  SELL: 'Venda',
  DEPOSIT: 'Aporte',
  WITHDRAWAL: 'Retirada',
};

interface BaseEntry {
  /** Unique across both types: the API's entry id. */
  id: string;
  date: IsoDate;
  time: IsoTime;
  entryType: EntryType;
  /** The backend's signed cash effect (`cash_amount`). */
  signedAmount: Decimal;
}

interface TradeEntry extends BaseEntry {
  kind: 'trade';
  instrumentTypeCode: string;
  assetCode: string;
  signedQuantity: number;
  pu: Decimal;
  rate: Decimal;
}

interface CashEntry extends BaseEntry {
  kind: 'cash';
}

export type LedgerEntry = TradeEntry | CashEntry;

export type SortDirection = 'asc' | 'desc';

/** Compra/venda by the sign of the quantity; aporte/retirada by the sign of the amount. */
export function toRow(entry: ApiLedgerEntry): LedgerEntry {
  const base = {
    id: entry.id,
    date: entry.date,
    time: entry.time,
    signedAmount: entry.cash_amount,
  };
  if (entry.type === 'TRADE') {
    return {
      ...base,
      kind: 'trade',
      entryType: entry.signed_quantity > 0 ? 'BUY' : 'SELL',
      instrumentTypeCode: entry.instrument_type_code,
      assetCode: entry.asset_code,
      signedQuantity: entry.signed_quantity,
      pu: entry.execution_pu,
      rate: entry.execution_rate,
    };
  }
  return {
    ...base,
    kind: 'cash',
    entryType: entry.cash_amount.startsWith('-') ? 'WITHDRAWAL' : 'DEPOSIT',
  };
}

/**
 * Names a row for screen readers and the delete dialogs, with enough of its figures to tell
 * same-day entries apart: "Venda DI1F28 -4 16/10/2026 15:00 PU 89.102,22",
 * "Retirada 16/10/2026 17:30 -R$ 50.000,00".
 */
export function entryLabel(entry: LedgerEntry): string {
  const type = ENTRY_TYPE_LABELS[entry.entryType];
  const when = `${formatDate(entry.date)} ${formatTime(entry.time)}`;
  if (entry.kind === 'cash') return `${type} ${when} ${formatSignedMoney(entry.signedAmount)}`;
  const quantity = formatSignedQuantity(entry.signedQuantity);
  return `${type} ${entry.assetCode} ${quantity} ${when} PU ${formatPu(entry.pu)}`;
}
