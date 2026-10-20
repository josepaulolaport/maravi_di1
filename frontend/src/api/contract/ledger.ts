import type { Decimal, Fits, InputKind, IsoDate, IsoTime, Schemas } from './common';

// Ledger (spec §6, OQ-24): trades and cash movements are one entry type.

export type TradeLedgerEntry = Schemas['TradeEntryResponse'];
/** An aporte (`cash_amount` > 0) or a retirada (< 0), with an optional description (OQ-51). */
export type CashLedgerEntry = Schemas['CashEntryResponse'];
export type LedgerEntry = TradeLedgerEntry | CashLedgerEntry;
export type LedgerEntryType = LedgerEntry['type'];
export type LedgerOrder = Schemas['ListOrder'];

/** PU **or** rate is typed (OQ-19 item 7); the schema flattens this choice into optionals. */
export type CreateTradeEntryRequest = {
  type: 'TRADE';
  asset_id: string;
  date: IsoDate;
  time: IsoTime;
  signed_quantity: number;
} & (
  | { input_kind: Extract<InputKind, 'PU'>; execution_pu: Decimal }
  | { input_kind: Extract<InputKind, 'RATE'>; execution_rate: Decimal }
);

export interface CreateCashEntryRequest {
  type: 'CASH';
  date: IsoDate;
  time: IsoTime;
  cash_amount: Decimal;
  description?: string | null;
}

export type CreateLedgerEntryRequest = Fits<
  CreateTradeEntryRequest | CreateCashEntryRequest,
  Schemas['CreateLedgerEntryBody']
>;

export type DeleteLedgerEntriesRequest = Schemas['DeleteLedgerEntriesBody'];
