import type { Schemas } from './common';

// Portfolio reads (spec §8, §11.4; OQ-21, OQ-23, OQ-31, OQ-41, OQ-49). The backend types every
// status as an enum, so nothing here is narrowed.

/** A date's processing status for one chain, NOT_PROCESSED without one (OQ-23, OQ-31). */
export type DateStatus = Schemas['ShownChainStatus'];
export type CompletenessStatus = Schemas['CalculationCompleteness'];
export type AssetValuationStatus = Schemas['ValuationStatus'];

export type CashSummary = Schemas['CashSummaryResponse'];
export type PositionsSummary = Schemas['PositionsSummaryResponse'];
export type PortfolioSummary = Schemas['PortfolioSummaryResponse'];
export type PositionRow = Schemas['PositionRowResponse'];
export type PortfolioPositions = Schemas['PortfolioPositionsResponse'];
export type PnlPoint = Schemas['PnlPointResponse'];
