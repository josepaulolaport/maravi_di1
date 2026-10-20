import type { Narrow, Schemas } from './common';
import type { PriceSource } from './prices';

// Portfolio reads (spec §8, §11.4; OQ-21, OQ-23, OQ-31, OQ-41, OQ-49). The backend types the
// statuses below as `string`; their values are the contract's.

/** A date's processing status for one chain (OQ-23, OQ-31). */
export type DateStatus = Exclude<Schemas['PredecessorState'], 'ZERO_STATE'>;
export type CompletenessStatus = 'COMPLETE' | 'MISSING';
export type AssetValuationStatus = CompletenessStatus | 'NOT_REQUIRED';

export type CashSummary = Narrow<Schemas['CashSummaryOut'], { status: DateStatus }>;

export type PositionsSummary = Narrow<
  Schemas['PositionsSummaryOut'],
  {
    status: DateStatus;
    valuation_status: CompletenessStatus | null;
    pnl_status: CompletenessStatus | null;
  }
>;

export type PortfolioSummary = Narrow<
  Schemas['PortfolioSummaryOut'],
  { cash: CashSummary; positions: PositionsSummary }
>;

export type PositionRow = Narrow<
  Schemas['PositionRowOut'],
  {
    reference_source: PriceSource | null;
    valuation_status: AssetValuationStatus;
    pnl_status: CompletenessStatus;
  }
>;

export type PortfolioPositions = Narrow<
  Schemas['PortfolioPositionsOut'],
  { status: DateStatus; items: PositionRow[] }
>;

export type PnlPoint = Narrow<Schemas['PnlPointOut'], { status: DateStatus }>;
