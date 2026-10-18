import type { Decimal, InputKind, IsoDate, IsoDateTime, IsoTime } from './common';

// Ledger (spec §6, schema `ledger.*`). Lançamentos screen (§11.3, OQ-19).

/** `GET /trades?start_date&end_date&search` — active (not deleted) trades, inclusive range. */
export interface Trade {
  id: string;
  asset_id: string;
  /** Proposal: denormalised instrument code (e.g. DI1F28) for the table and search. */
  asset_code: string;
  /** Proposal: the instrument type (e.g. FUTURE), shown as "Tipo de ativo" (§11.3). */
  instrument_type_code: string;
  trade_date: IsoDate;
  /** São Paulo local time (OQ-13). */
  trade_time: IsoTime;
  /** Tie-breaker within (trade_date, trade_time). */
  seq: number;
  /** Positive = compra, negative = venda. */
  signed_quantity: number;
  execution_pu: Decimal;
  /** Stored as 0 on the maturity date (OQ-1). */
  execution_rate: Decimal;
  /** Which value the user typed; the other was computed on save (OQ-19 item 7). */
  input_kind: InputKind;
  /**
   * Proposal: the trade's cash effect, `−signed_quantity × execution_pu` (§7.3), computed by
   * the backend so the browser never multiplies money ("Valor financeiro").
   */
  cash_amount: Decimal;
  created_at: IsoDateTime;
}

export type CashMovementType = 'DEPOSIT' | 'WITHDRAWAL';

/** `GET /cash-movements?start_date&end_date&search`. */
export interface CashMovement {
  id: string;
  movement_date: IsoDate;
  movement_type: CashMovementType;
  /** Always positive; the type gives the direction (§6.2). */
  amount: Decimal;
  description: string | null;
  created_at: IsoDateTime;
}

/** `POST /trades`: exactly one of PU or rate is typed (§4.1). */
export type CreateTradeRequest = {
  asset_id: string;
  trade_date: IsoDate;
  trade_time: IsoTime;
  signed_quantity: number;
} & ({ input_kind: 'PU'; execution_pu: Decimal } | { input_kind: 'RATE'; execution_rate: Decimal });

/** `POST /cash-movements`. */
export interface CreateCashMovementRequest {
  movement_date: IsoDate;
  movement_type: CashMovementType;
  amount: Decimal;
  description?: string;
}

/**
 * Proposal: `POST /ledger/deletions` soft-deletes several entries in one transaction
 * (§6.1 "exclusão múltipla com confirmação e operação atômica"). Single deletes keep using
 * `DELETE /trades/{id}` and `DELETE /cash-movements/{id}`.
 */
export interface DeleteEntriesRequest {
  trade_ids: string[];
  cash_movement_ids: string[];
  reason?: string;
}

/**
 * Proposal (P18): `GET /ledger/entries?start_date&end_date&search&order` — the Lançamentos
 * list, trades and cash movements in one response, filtered and ordered by the backend.
 * Default order (`desc`): newest date first; within a date, trades by (time, seq), newest
 * first, then cash movements, which have no time (GAP-I-1), newest recorded first. `asc` is
 * the exact reverse. Writes keep their own endpoints.
 */
interface LedgerEntryBase {
  id: string;
  /** `trade_date` or `movement_date`. */
  date: IsoDate;
  /**
   * The entry's signed cash effect, computed by the backend: a trade's `cash_amount`
   * (−signed_quantity × execution_pu), +amount for an aporte, −amount for a retirada.
   */
  cash_amount: Decimal;
  created_at: IsoDateTime;
}

export interface TradeLedgerEntry extends LedgerEntryBase {
  kind: 'TRADE';
  time: IsoTime;
  seq: number;
  asset_id: string;
  asset_code: string;
  instrument_type_code: string;
  signed_quantity: number;
  execution_pu: Decimal;
  execution_rate: Decimal;
  input_kind: InputKind;
}

export interface CashLedgerEntry extends LedgerEntryBase {
  kind: 'CASH_MOVEMENT';
  /** Cash movements have no time (GAP-I-1). */
  time: null;
  movement_type: CashMovementType;
  /** Always positive; `cash_amount` carries the direction. */
  amount: Decimal;
}

export type LedgerEntry = TradeLedgerEntry | CashLedgerEntry;

export type LedgerOrder = 'asc' | 'desc';
