import type { IsoDate, IsoDateTime } from './common';
import type { Freshness } from './portfolio';

// Processing (spec §10, schema `processing.*`). Central de Controle (§11.1, OQ-20).

/**
 * Cash and positions are two daily chains processed separately (OQ-21). A request processes the cash chain,
 * the positions chain (quantities, averages, valuation and P&L) or both.
 */
export type ProcessingScope = 'CASH' | 'POSITIONS' | 'ALL';

/** One of the two daily chains (OQ-21). */
export type ProcessingChain = 'CASH' | 'POSITIONS';

export type JobStatus =
  | 'QUEUED'
  | 'DISPATCHED'
  | 'RUNNING'
  | 'CANCELLING'
  | 'CANCELLED'
  | 'COMPLETED'
  | 'COMPLETED_WITH_ISSUES'
  | 'FAILED';

/**
 * `GET /processing/requests?limit&cursor` (newest first, by (created_at, id); a `Page`, P21),
 * `GET /processing/requests/{id}`.
 */
export interface ProcessingRequest {
  id: string;
  /** The chain(s) this run processes (OQ-21). */
  scope: ProcessingScope;
  /** The run processes exactly this range, in calendar order (OQ-11, OQ-23). */
  start_date: IsoDate;
  end_date: IsoDate;
  status: JobStatus;
  /**
   * The last date the run committed (OQ-23): each date is published on its own, so every date
   * up to it stays published whatever the run's end. `null` before the first one. Days done
   * and the date being processed derive from it and the range.
   */
  progress_date: IsoDate | null;
  error_code: string | null;
  /** pt-BR, for FAILED. */
  error_message: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  dispatched_at: IsoDateTime | null;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  cancel_requested_at: IsoDateTime | null;
}

/** `POST /processing/requests` and the preview. */
export interface ProcessingRangeRequest {
  start_date: IsoDate;
  end_date: IsoDate;
  /** Required (OQ-21). */
  scope: ProcessingScope;
}

/**
 * The day before the range, per chain (OQ-11, OQ-26 item 8): its chain status (`Freshness`),
 * or ZERO_STATE when the chain has nothing before it (positions: no trade; cash: no entry of
 * either type). Unless it is FRESH, FRESH_WITH_ISSUES or ZERO_STATE, the run's dates are
 * written STALE with a STALE_PREDECESSOR issue; a cash day never processed refuses a CASH or
 * ALL run when it starts (OQ-22).
 */
export type PredecessorState = Freshness | 'ZERO_STATE';

/** Proposal: `GET /processing/preview?start_date&end_date` (`ProcessingService.preview_range`). */
export interface ProcessingPreview {
  start_date: IsoDate;
  end_date: IsoDate;
  total_days: number;
  scope: ProcessingScope;
  predecessor_date: IsoDate;
  /** The day before the range, for each chain of the scope (OQ-11, OQ-26). */
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
  /** For STALE_PREDECESSOR, the chain whose day before is not current; else `null` (OQ-22). */
  chain: ProcessingChain | null;
  request_id: string;
}
