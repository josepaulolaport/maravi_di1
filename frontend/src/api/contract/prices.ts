import type { Decimal, InputKind, IsoDate, IsoDateTime } from './common';

// Prices (spec §5, schema `prices.reference_prices`). Contract page (§11.2, OQ-19 item 6).

/** MANUAL wins over B3 for the same asset and date (§5). */
export type PriceSource = 'MANUAL' | 'B3';

/** One immutable observation revision. */
export interface ReferencePrice {
  id: string;
  asset_id: string;
  reference_date: IsoDate;
  source: PriceSource;
  input_kind: InputKind;
  pu: Decimal;
  rate: Decimal | null;
  revision: number;
  created_at: IsoDateTime;
  /** Set when a correction or removal replaced this revision. */
  superseded_at: IsoDateTime | null;
}

/**
 * Proposal: `GET /reference-prices?asset_id&start_date&end_date` returns one entry per date
 * that has at least one current observation. The backend applies MANUAL > B3 (`preferred`);
 * dates without an observation are absent, and the calendar shows them as such (no carry-forward).
 */
export interface ReferencePriceDay {
  reference_date: IsoDate;
  preferred: ReferencePrice;
  /** The current revision of each source for that date. */
  current: ReferencePrice[];
}

/**
 * `POST /reference-prices`: records a MANUAL observation. If a current MANUAL revision exists
 * for the asset and date, it is superseded by a new revision (a correction, §5).
 */
export type SetReferencePriceRequest = {
  asset_id: string;
  reference_date: IsoDate;
} & ({ input_kind: 'PU'; pu: Decimal } | { input_kind: 'RATE'; rate: Decimal });

// `DELETE /reference-prices/{id}`: audit-preserving removal of a current revision.
// Proposal: `GET /reference-prices/revisions?asset_id&reference_date` lists every revision
// of both sources, newest first ("Ver revisões"): ListResponse<ReferencePrice>.
