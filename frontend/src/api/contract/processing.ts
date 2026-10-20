import type { Schemas } from './common';

// Processing (spec §10; OQ-20, OQ-21, OQ-23, OQ-36, OQ-37, OQ-40, OQ-46).

export type ProcessingScope = Schemas['ProcessingScope'];
export type ProcessingChain = Schemas['Chain'];
/** Eight statuses (OQ-23); DISPATCHED and CANCELLING are never set since OQ-46. */
export type JobStatus = Schemas['ProcessingStatus'];
export type ProcessingRequest = Schemas['ProcessingRequestResponse'];
export type ProcessingRangeRequest = Schemas['ProcessingRangeRequest'];
/** The day before a range, per chain: its date status, or the chain's zero state (OQ-26). */
export type PredecessorState = Schemas['PredecessorState'];
export type ProcessingPreview = Schemas['ProcessingPreviewResponse'];
export type IssueType = Schemas['IssueType'];
export type Issue = Schemas['IssueResponse'];
