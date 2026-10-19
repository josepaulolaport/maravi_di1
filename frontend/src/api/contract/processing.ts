import type { IsoDate, IsoDateTime } from './common';

// Processing (spec §10, schema `processing.*`). Central de Controle (§11.1, OQ-20).

/**
 * DRAFT (OQ-21, user 2026-10-18; names to align with lane X's interfaces.md): cash and
 * positions are two daily chains processed separately. A request processes the cash chain,
 * the positions chain (quantities, averages, valuation and P&L) or both.
 */
export type ProcessingScope = 'CASH' | 'POSITIONS' | 'ALL';

/** One of the two daily chains (OQ-21 draft). */
export type ProcessingChain = 'CASH' | 'POSITIONS';

export type JobStatus =
  | 'QUEUED'
  | 'DISPATCHED'
  | 'RUNNING'
  | 'CANCELLING'
  | 'CANCELLED'
  | 'COMPLETED'
  | 'COMPLETED_WITH_ISSUES'
  | 'FAILED'
  | 'SUPERSEDED';

/**
 * `GET /processing/requests?limit&cursor` (newest first, by (created_at, id); a `Page`, P21),
 * `GET /processing/requests/{id}`.
 */
export interface ProcessingRequest {
  id: string;
  /** The job processes exactly this range (OQ-11). */
  requested_start_date: IsoDate;
  requested_end_date: IsoDate;
  /** Draft (OQ-21): the chain(s) this job recomputes and publishes. */
  scope: ProcessingScope;
  status: JobStatus;
  created_at: IsoDateTime;
  dispatched_at: IsoDateTime | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  cancel_requested_at: IsoDateTime | null;
  /** Days staged so far ("x / y dias"); nothing is published before the end (§10.4). */
  processed_days: number;
  total_days: number;
  /** The date being processed while RUNNING. */
  progress_date: IsoDate | null;
  error_code: string | null;
  /** pt-BR, for FAILED. */
  error_message: string | null;
}

/** `POST /processing/requests` and the preview. */
export interface ProcessingRangeRequest {
  start_date: IsoDate;
  end_date: IsoDate;
  /** Draft (OQ-21): required. */
  scope: ProcessingScope;
}

/**
 * State of the day before the range (OQ-11): ZERO_STATE when nothing was recorded before it
 * (valid), VALID when published and current, STALE or NOT_PROCESSED otherwise (the job still
 * runs, and its days read as stale with a STALE_PREDECESSOR issue).
 */
export type PredecessorState = 'ZERO_STATE' | 'VALID' | 'STALE' | 'NOT_PROCESSED';

/** Proposal: `GET /processing/preview?start_date&end_date` (`ProcessingService.preview_range`). */
export interface ProcessingPreview {
  start_date: IsoDate;
  end_date: IsoDate;
  total_days: number;
  scope: ProcessingScope;
  predecessor_date: IsoDate;
  /** Draft (OQ-21): the state of the day before the range, for each chain. */
  predecessor: { cash: PredecessorState; positions: PredecessorState };
}

/** `POST /processing/requests/{id}/cancel-and-replace` (§10.2). */
export interface CancelAndReplaceResponse {
  cancelled: ProcessingRequest;
  replacement: ProcessingRequest;
}

export type IssueType = 'MISSING_REFERENCE_PRICE' | 'EXPIRED_OPEN_POSITION' | 'STALE_PREDECESSOR';

/**
 * Proposal: `GET /processing/issues` — the current, deduplicated Pendências (§10.3): the issues
 * of the latest publication covering each date. Exactly three types (OQ-19 item 2).
 */
export interface Issue {
  id: string;
  issue_type: IssueType;
  asset_id: string | null;
  asset_code: string | null;
  affected_date: IsoDate;
  /** For MISSING_REFERENCE_PRICE: the exact date whose price is needed ("Definir preço"). */
  required_price_date: IsoDate | null;
  /** Draft (OQ-21): for STALE_PREDECESSOR, the chain whose day before is stale; else `null`. */
  chain: ProcessingChain | null;
  request_id: string;
}
