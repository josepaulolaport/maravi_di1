import type { Decimal, Fits, InputKind, IsoDate, Schemas } from './common';

// Reference prices (spec §5; OQ-25, OQ-26, OQ-30).

export type PriceSource = Schemas['PriceSource'];
export type ReferencePrice = Schemas['ReferencePriceResponse'];
/** A date's preferred observation (MANUAL over B3) and every current one (P8). */
export type ReferencePriceDay = Schemas['ReferencePriceDayResponse'];

/** PU **or** rate is typed (§4.1); the schema flattens this choice into optionals. */
export type SetReferencePriceRequest = Fits<
  { asset_id: string; reference_date: IsoDate } & (
    | { input_kind: Extract<InputKind, 'PU'>; pu: Decimal }
    | { input_kind: Extract<InputKind, 'RATE'>; rate: Decimal }
  ),
  Schemas['SetReferencePriceRequest']
>;
