import type { Decimal, InputKind, IsoDate, IsoDateTime } from './common';

// Prices (spec §5, schema `prices.reference_prices`). Contract page (§11.2, OQ-19 item 6).
//
// No revisions (user, 2026-10-18: "drop the revision. we will not be needing it anymore"):
// there is one price per (asset, date, source); adding a price replaces the current one and a
// removal deletes it (OQ-25, OQ-26 item 7).

/** MANUAL wins over B3 for the same asset and date (§5). */
export type PriceSource = 'MANUAL' | 'B3';

/** The price of one source for an asset and date. */
export interface ReferencePrice {
  id: string;
  asset_id: string;
  reference_date: IsoDate;
  source: PriceSource;
  input_kind: InputKind;
  pu: Decimal;
  rate: Decimal | null;
  created_at: IsoDateTime;
}

/**
 * Proposal: `GET /reference-prices?asset_id&start_date&end_date` returns one entry per date
 * that has at least one price. The backend applies MANUAL > B3 (`preferred`); dates without a
 * price are absent, and the calendar shows them as such (no carry-forward).
 */
export interface ReferencePriceDay {
  reference_date: IsoDate;
  preferred: ReferencePrice;
  /** The price of each source for that date (at most one each). */
  sources: ReferencePrice[];
}

/**
 * `POST /reference-prices`: records the MANUAL price of an asset and date (201). An existing
 * one for the same asset, date and source is deleted first, so the price gets a new id
 * (OQ-26 item 7); Corrigir works this way. The dependent results go stale (§10.4).
 */
export type SetReferencePriceRequest = {
  asset_id: string;
  reference_date: IsoDate;
} & ({ input_kind: 'PU'; pu: Decimal } | { input_kind: 'RATE'; rate: Decimal });

// `DELETE /reference-prices/{id}`: deletes that price (204).
