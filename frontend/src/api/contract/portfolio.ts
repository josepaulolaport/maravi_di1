import type { Decimal, IsoDate, IsoDateTime } from './common';
import type { PriceSource } from './prices';

// Portfolio read model (spec §8, §9, §11.4, §12). Published data only; never recalculated
// on GET. `null` means unavailable, never zero.

export type CompletenessStatus = 'COMPLETE' | 'MISSING';
export type AssetValuationStatus = CompletenessStatus | 'NOT_REQUIRED';

/**
 * The status of one chain on one date (OQ-23, `processing.date_status`), the only source of
 * freshness; every portfolio read and both badges use it:
 * - FRESH (Atualizado) and FRESH_WITH_ISSUES (Atualizado com pendências: a missing price or an
 *   expired open position);
 * - STALE (Desatualizado): an input changed after publication, or the day before was not
 *   current when it was processed; the figures are still shown, flagged (§8.3);
 * - RUNNING (Processando): a run is processing the date now;
 * - FAILED (Erro): the last attempt failed; the date keeps its previously published data;
 * - NOT_PROCESSED (Não processado): no status yet.
 */
export type Freshness =
  'FRESH' | 'FRESH_WITH_ISSUES' | 'STALE' | 'RUNNING' | 'FAILED' | 'NOT_PROCESSED';

/** The cash chain of a date (OQ-21): `portfolio.cash_balances`. */
export interface CashSummary {
  status: Freshness;
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
  published_at: IsoDateTime | null;
}

/** The positions chain of a date (OQ-21): valuation and P&L, `portfolio_metrics`. */
export interface PositionsSummary {
  status: Freshness;
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
   * The reference PU this publication used and its source (OQ-25): stored on the published
   * row, so the day stays traceable after the price is corrected or removed. Null when there
   * is no price or the date is after maturity.
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
 * positions chain's freshness (OQ-21). Not processed: no rows, no publication time.
 */
export interface PortfolioPositions {
  date: IsoDate;
  status: Freshness;
  published_at: IsoDateTime | null;
  items: PositionRow[];
}

/** One published day of `GET /portfolio/pnl?start_date&end_date` (OQ-16), positions chain. */
export interface PnlPoint {
  date: IsoDate;
  daily_pnl: Decimal | null;
  cumulative_pnl: Decimal | null;
  pnl_status: CompletenessStatus;
  /** The date's positions status; only published days are listed, so never NOT_PROCESSED. */
  status: Freshness;
}
