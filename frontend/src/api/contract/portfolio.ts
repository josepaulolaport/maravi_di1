import type { Decimal, IsoDate, IsoDateTime } from './common';
import type { PriceSource } from './prices';

// Portfolio read model (spec §8, §9, §11.4, §12). Published data only; never recalculated
// on GET. `null` means unavailable, never zero.

export type CompletenessStatus = 'COMPLETE' | 'MISSING';
export type AssetValuationStatus = CompletenessStatus | 'NOT_REQUIRED';

/**
 * Proposal: every portfolio response says whether the date was ever published, and whether
 * what was published is stale (an input changed afterwards: date ≥ a dirty marker, §10.4).
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

/** `GET /portfolio/summary?date=` (`portfolio.portfolio_metrics`). */
export type PortfolioSummary =
  | NotProcessed
  | (Published & {
      cash_balance: Decimal;
      positions_market_value: Decimal | null;
      /** AUM = cash + Σ signed market value (§8.2). */
      aum: Decimal | null;
      position_pnl: Decimal | null;
      trades_pnl: Decimal | null;
      daily_pnl: Decimal | null;
      /** Unavailable from the first unresolved gap onward (§8.3). */
      cumulative_pnl: Decimal | null;
      valuation_status: CompletenessStatus;
      pnl_status: CompletenessStatus;
    });

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

/** `GET /portfolio/positions?date=` — rows and totals come from the same publication. */
export type PortfolioPositions = NotProcessed | (Published & { items: PositionRow[] });

/** One published day of `GET /portfolio/pnl?start_date&end_date` (OQ-16). */
export interface PnlPoint {
  date: IsoDate;
  daily_pnl: Decimal | null;
  cumulative_pnl: Decimal | null;
  pnl_status: CompletenessStatus;
  stale: boolean;
}
