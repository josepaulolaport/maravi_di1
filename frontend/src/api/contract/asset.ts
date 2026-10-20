import type { Schemas } from './common';

// Asset (spec §3, schema `asset.*`). Ativos screen (§11.2, OQ-19).

export type AssetClass = Schemas['AssetClassOut'];
export type InstrumentType = Schemas['InstrumentTypeOut'];
export type FuturesSpec = Schemas['FuturesSpecOut'];
export type Product = Schemas['ProductOut'];
/** A contract's latest reference observation, always shown with its own date (OQ-48). */
export type LastReference = Schemas['LastReferenceOut'];
export type Instrument = Schemas['InstrumentOut'];
export type CreateInstrumentRequest = Schemas['CreateInstrumentIn'];
