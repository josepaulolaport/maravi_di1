import type { Decimal, IsoDate, IsoDateTime } from './common';
import type { PriceSource } from './prices';

// Portfolio read model (spec §8, §9, §11.4, §12). Published data only; never recalculated
// on GET. `null` means unavailable, never zero.

export type CompletenessStatus = 'COMPLETE' | 'MISSING';
export type AssetValuationStatus = CompletenessStatus | 'NOT_REQUIRED';

/**
 * Proposal: a portfolio response says whether the date was ever published, and whether what
 * was published is stale (an input changed afterwards: date ≥ a dirty marker, §10.4).
 */
interface NotProcessed {
  date: IsoDate;
  publication: 'NOT_PROCESSED';
}

interface Published {
  date: IsoDate;
  publication: 'PUBLISHED';
  /** True when an input changed after publication; figures stay visible, flagged (§8.3). */
  stale: boolean;
  published_at: IsoDateTime;
}

/**
 * DRAFT (OQ-21): how current one chain's published result for a date is. FRESH: published and
 * current; STALE: published, but an input changed afterwards; NOT_PROCESSED: never published.
 */
export type Freshness = 'FRESH' | 'STALE' | 'NOT_PROCESSED';

/** The cash chain of a date (OQ-21 draft): `portfolio.cash_balances`. */
export interface CashSummary {
  status: Freshness;
  /** `null` when not processed. */
  balance: Decimal | null;
  published_at: IsoDateTime | null;
}

/** The positions chain of a date (OQ-21 draft): valuation and P&L, `portfolio_metrics`. */
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

/**
 * AUM = cash + market value (§8.2), where the two chains meet (OQ-21 draft): `null` when either
 * side is missing; NOT_PROCESSED when either side is, STALE when either side is stale.
 */
export interface AumSummary {
  status: Freshness;
  value: Decimal | null;
}

/** `GET /portfolio/summary?date=` (OQ-21 draft shape). */
export interface PortfolioSummary {
  date: IsoDate;
  cash: CashSummary;
  positions: PositionsSummary;
  aum: AumSummary;
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
  /** The observation used, traceable to its revision (§5). Null when missing or after maturity. */
  reference_price_id: string | null;
  /** Proposal: source and rate of that observation, read through `reference_price_id`. */
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
 * `GET /portfolio/positions?date=` — rows and totals come from the same publication. Its
 * `publication`/`stale` describe the positions chain (OQ-21 draft); lane X may align it with
 * `Freshness` (proposal).
 */
export type PortfolioPositions = NotProcessed | (Published & { items: PositionRow[] });

/** One published day of `GET /portfolio/pnl?start_date&end_date` (OQ-16); `stale` is the positions chain's. */
export interface PnlPoint {
  date: IsoDate;
  daily_pnl: Decimal | null;
  cumulative_pnl: Decimal | null;
  pnl_status: CompletenessStatus;
  stale: boolean;
}
