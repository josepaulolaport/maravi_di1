import type { Decimal, InputKind, IsoDate, IsoDateTime, IsoTime } from './common';

// Ledger (spec §6, schema `ledger.*`). Lançamentos screen (§11.3, OQ-19).
//
// One kind of record, the ledger entry (user, 2026-10-18: "Their separation should be their
// type only"). A TRADE moves a position and cash; a CASH entry (aporte or retirada) moves only
// cash. Both live under `/ledger/entries`: listed, created and deleted the same way.

/** TRADE: compra or venda (the sign of the quantity). CASH: aporte or retirada (the sign of the amount). */
export type LedgerEntryType = 'TRADE' | 'CASH';

interface LedgerEntryBase {
  id: string;
  type: LedgerEntryType;
  date: IsoDate;
  /** São Paulo local time, required on every entry (OQ-13; user 2026-10-18, closes GAP-I-1). */
  time: IsoTime;
  /** Tie-breaker within (date, time), shared by both types. */
  seq: number;
  /**
   * The entry's signed cash effect, from the backend: −signed_quantity × execution_pu for a
   * trade (§7.3); for a cash entry, the amount itself, + aporte, − retirada (§6.2).
   */
  cash_amount: Decimal;
  created_at: IsoDateTime;
}

export interface TradeLedgerEntry extends LedgerEntryBase {
  type: 'TRADE';
  asset_id: string;
  /** Denormalised instrument code (e.g. DI1F28) for the table and search. */
  asset_code: string;
  /** The instrument type (e.g. FUTURE), shown as "Tipo de ativo" (§11.3). */
  instrument_type_code: string;
  /** Positive = compra, negative = venda. */
  signed_quantity: number;
  execution_pu: Decimal;
  /** Stored as 0 on the maturity date (OQ-1). */
  execution_rate: Decimal;
  /** Which value the user typed; the other was computed on save (OQ-19 item 7). */
  input_kind: InputKind;
}

/** Aporte (positive `cash_amount`) or retirada (negative). No description (GAP-I-2). */
export interface CashLedgerEntry extends LedgerEntryBase {
  type: 'CASH';
}

export type LedgerEntry = TradeLedgerEntry | CashLedgerEntry;

/**
 * `GET /ledger/entries?start_date&end_date&search&order` (P18): both types in one list,
 * filtered and ordered by the backend, by (date, time, seq); `desc` (default) newest first,
 * `asc` the exact reverse.
 */
export type LedgerOrder = 'asc' | 'desc';

/** `POST /ledger/entries`, TRADE: exactly one of PU or rate is typed (§4.1). */
export type CreateTradeEntryRequest = {
  type: 'TRADE';
  asset_id: string;
  date: IsoDate;
  time: IsoTime;
  signed_quantity: number;
} & ({ input_kind: 'PU'; execution_pu: Decimal } | { input_kind: 'RATE'; execution_rate: Decimal });

/** `POST /ledger/entries`, CASH: the signed amount, at most 2 places, never zero (§6.2, OQ-3). */
export interface CreateCashEntryRequest {
  type: 'CASH';
  date: IsoDate;
  time: IsoTime;
  cash_amount: Decimal;
}

/** `POST /ledger/entries` returns the created `LedgerEntry` (201). */
export type CreateLedgerEntryRequest = CreateTradeEntryRequest | CreateCashEntryRequest;

/**
 * `POST /ledger/entries/deletions` (lane X, 2026-10-18; a POST, since a DELETE body is not
 * reliably carried by proxies): soft-deletes the entries, whatever their type, in
 * one transaction; an unknown id deletes nothing (§6.1 "operação atômica"). 204.
 */
export interface DeleteLedgerEntriesRequest {
  ids: string[];
}
