// Draft API contract (lane I). Field names follow docs/schema.sql; anything the docs do not
// name is a contract proposal for the integrator, listed in the PR. At Wave 5 these
// hand-written types are replaced by types generated from the backend's OpenAPI.

/**
 * A decimal number as a JSON string ("89006.4625467350"), never a float (CLAUDE.md §2).
 * The frontend only formats it; it never does arithmetic on it.
 */
export type Decimal = string;

/** A calendar date, `YYYY-MM-DD`. */
export type IsoDate = string;

/** A local São Paulo time, `HH:MM:SS`. */
export type IsoTime = string;

/** An instant with offset, ISO 8601. */
export type IsoDateTime = string;

/** Proposal: every list response is wrapped, so metadata can be added without a break. */
export interface ListResponse<T> {
  items: T[];
}

/**
 * A page of a keyset-paginated list (lane X, approved by the user 2026-10-18): the ledger
 * entries, ordered by (date, time, seq), and the jobs, by (created_at, id). `next_cursor` is
 * opaque; `null` on the last page. There is no total count.
 */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

/** `?limit=&cursor=`: the page size, and the `next_cursor` of the previous page. */
// A type alias (not an interface) so it is assignable to the client's query record.
export type PageQuery = {
  limit?: number;
  cursor?: string;
};

/** One entry of `errors` in a problem+json body (docs/interfaces.md "Errors"). */
export interface FieldError {
  code: ErrorCode;
  /** pt-BR, shown to the user as is. */
  message: string;
  /** The request field it belongs to, or `null` for a page-level error. */
  field: string | null;
}

export type ErrorCode =
  | 'VALIDATION_ERROR'
  | 'FUTURE_DATE'
  | 'CONTRACT_MATURED'
  | 'NOT_FOUND'
  | 'INVALID_RANGE'
  | 'JOB_NOT_CANCELLABLE';

/** RFC 9457 `application/problem+json` (OQ-15). */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  errors?: FieldError[];
}

/** PU or rate: which one the user typed; the other is computed by the backend (§4.1). */
export type InputKind = 'PU' | 'RATE';
