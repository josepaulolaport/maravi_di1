import type { Decimal, IsoDate, IsoDateTime } from './common';
import type { PriceSource } from './prices';

// Asset (spec §3, schema `asset.*`). Ativos screen (§11.2, OQ-19).

export interface AssetClass {
  id: number;
  code: string; // e.g. INTEREST_RATE_FUTURE
  name: string;
}

/** Proposal: `GET /instrument-types` returns each type with its classes (the catalogue tabs). */
export interface InstrumentType {
  id: number;
  code: string; // e.g. FUTURE
  name: string;
  asset_classes: AssetClass[];
}

/** Shared futures specification (`asset.futures`). */
export interface FuturesSpec {
  face_value: Decimal;
  /** Stored, not applied in calculations (OQ-2). */
  contract_multiplier: Decimal;
  settlement_method: string;
  settlement_description: string | null;
  // No pricing-methodology field: DC/365 is the only convention (§4.1), so the product
  // page shows "Contagem de dias" as the fixed text "Dias corridos / 365".
}

/** `GET /products`, `GET /products/{id}`. */
export interface Product {
  id: string;
  code: string; // e.g. DI1
  name: string;
  /** Proposal: denormalised for the catalogue row. */
  asset_class: AssetClass;
  instrument_type: Omit<InstrumentType, 'asset_classes'>;
  /** Proposal: number of contracts, for the catalogue's "Contratos" column. */
  instrument_count: number;
  futures: FuturesSpec | null;
  created_at: IsoDateTime;
}

/**
 * Proposal (OQ-19 item 5): the instrument's latest current reference observation, preferred
 * source first. Always shown next to its own date; it is never "today's price" (§5).
 */
export interface LastReference {
  reference_date: IsoDate;
  pu: Decimal;
  rate: Decimal | null;
  source: PriceSource;
}

/** `GET /instruments`, `GET /instruments/{id}`. */
export interface Instrument {
  id: string;
  code: string; // e.g. DI1F28
  product_id: string;
  /** Proposal: denormalised for breadcrumbs and tables. */
  product_code: string;
  maturity_date: IsoDate | null;
  /** Always null for now (OQ-33 item 4), until Prices exposes a latest-observation read. */
  last_reference: LastReference | null;
  created_at: IsoDateTime;
}

/**
 * `POST /instruments` ("Novo contrato"). The code is trimmed and upper-cased; an unknown
 * `product_id` is 422 on that field (OQ-33 items 1–2).
 */
export interface CreateInstrumentRequest {
  product_id: string;
  code: string;
  maturity_date: IsoDate;
}
