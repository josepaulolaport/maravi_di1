import type { Schemas } from './common';

// Asset (spec §3, schema `asset.*`). Ativos screen (§11.2, OQ-19).

export type AssetClass = Schemas['AssetClassResponse'];
export type InstrumentType = Schemas['InstrumentTypeResponse'];
export type FuturesSpec = Schemas['FuturesSpecResponse'];
export type Product = Schemas['ProductResponse'];
/** A contract's latest reference observation, always shown with its own date (OQ-48). */
export type LastReference = Schemas['LastReferenceResponse'];
export type Instrument = Schemas['InstrumentResponse'];
export type CreateInstrumentRequest = Schemas['CreateInstrumentRequest'];
