import type { Decimal, IsoDate, IsoDateTime } from './common';
import type { PriceSource } from './prices';

// Portfolio read model (spec §8, §9, §11.4, §12). Published data only; never recalculated
// on GET. `null` means unavailable, never zero.

export type CompletenessStatus = 'COMPLETE' | 'MISSING';
export type AssetValuationStatus = CompletenessStatus | 'NOT_REQUIRED';

/**
 * The processing status of one chain on one date (OQ-23, OQ-31; `processing.date_status`).
 * There is no staleness: a write never changes it, and processed figures stay as they are until
 * the user processes again (spec §15).
 * - PROCESSED (Processado) and PROCESSED_WITH_ISSUES (Processado com pendências: a missing price
 *   or an expired open position);
 * - RUNNING (Processando): a run is processing the date now;
 * - FAILED (Erro): the last attempt failed (e.g. the day before was not processed); the date
 *   keeps its previously published data, if any;
 * - NOT_PROCESSED (Não processado): never processed.
 */
export type DateStatus =
  'PROCESSED' | 'PROCESSED_WITH_ISSUES' | 'RUNNING' | 'FAILED' | 'NOT_PROCESSED';

/** The cash chain of a date (OQ-21): `portfolio.cash_balances`. */
export interface CashSummary {
  status: DateStatus;
  /** `null` when not processed. */
  balance: Decimal | null;
  /**
   * The day's components (OQ-21; user 2026-10-18: "metrics we will need to calculate and
   * keep"): −Σ(signed_qty × execution_PU), the day's deposits and withdrawals. `null` when
   * not processed.
   */
  trades_cash_flow: Decimal | null;
  /** Sum of the day's aportes, always ≥ 0. */
  deposits: Decimal | null;
  /** Sum of the day's retiradas, always ≥ 0 and subtracted: balance = previous + trades_cash_flow + deposits − withdrawals. */
  withdrawals: Decimal | null;
  /** When the cash chain was last processed for the date (`cash_processed_at`, OQ-31); `null` if never. */
  published_at: IsoDateTime | null;
}

/** The positions chain of a date (OQ-21): valuation and P&L, `portfolio_metrics`. */
export interface PositionsSummary {
  status: DateStatus;
  /** When the positions chain was last processed for the date (`portfolio_processed_at`, OQ-31). */
  published_at: IsoDateTime | null;
  /** Σ signed market value (§8.2). */
  market_value: Decimal | null;
  valuation_status: CompletenessStatus | null;
  position_pnl: Decimal | null;
  trades_pnl: Decimal | null;
  daily_pnl: Decimal | null;
  /** Unavailable from the first unresolved gap onward (§8.3). */
  cumulative_pnl: Decimal | null;
  pnl_status: CompletenessStatus | null;
}

/** `GET /portfolio/summary?date=` (OQ-21). */
export interface PortfolioSummary {
  date: IsoDate;
  cash: CashSummary;
  positions: PositionsSummary;
  /**
   * AUM = cash + market value (§8.2), where the two chains meet (OQ-21): `null` when either
   * side is missing. It has no status of its own (user, 2026-10-19): the Caixa and Posições
   * badges tell how current its two sides are.
   */
  aum: Decimal | null;
}

/** One row of the positions table: an expected asset on the date (OQ-10). */
export interface PositionRow {
  asset_id: string;
  asset_code: string;
  maturity_date: IsoDate | null;
  /** Signed closing quantity; 0 after a full close on the day. */
  quantity: number;
  average_entry_pu: Decimal | null;
  average_entry_rate: Decimal | null;
  /**
   * The date's current preferred reference price, read from the price table (OQ-30): MANUAL,
   * else B3, exact date; after maturity the PU is 0. After a correction it shows the new price
   * next to figures computed with the old one, until the date is processed again.
   */
  reference_source: PriceSource | null;
  reference_pu: Decimal | null;
  reference_rate: Decimal | null;
  /** Market value, Q × reference PU (§8.2). */
  financial_total: Decimal | null;
  position_pnl: Decimal | null;
  trades_pnl: Decimal | null;
  daily_pnl: Decimal | null;
  valuation_status: AssetValuationStatus;
  pnl_status: CompletenessStatus;
}

/**
 * `GET /portfolio/positions?date=` — rows and totals come from the same publication, with the
 * positions chain's status and processing time (OQ-21, OQ-31). Not processed: no rows, no publication time.
 */
export interface PortfolioPositions {
  date: IsoDate;
  status: DateStatus;
  published_at: IsoDateTime | null;
  items: PositionRow[];
}

/**
 * One calendar day of `GET /portfolio/pnl?start_date&end_date` (OQ-16, OQ-41, OQ-49), positions
 * chain: the series has a point for every date of the range. Only a PROCESSED or
 * PROCESSED_WITH_ISSUES day carries its daily P&L; any other day has `daily_pnl` null.
 * The since-inception cumulative and the processing time stay on the summary.
 */
export interface PnlPoint {
  date: IsoDate;
  daily_pnl: Decimal | null;
  /**
   * Σ daily P&L from the requested `start_date` to this date, the start's own included, summed
   * by the backend on each request (OQ-31 item 8): what the Carteira chart draws. Never null: a
   * day adds its daily P&L only when it is processed and the P&L is not null, and 0 otherwise
   * (OQ-41 items 1 and 4).
   */
  range_cumulative_pnl: Decimal;
  /** The date's positions status: NOT_PROCESSED on a day never processed (OQ-41 item 2). */
  status: DateStatus;
}
