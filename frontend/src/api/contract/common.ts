import type { components } from '../generated/schema';

// The HTTP contract, as the app uses it. Every response and request type is the backend's
// OpenAPI schema (src/api/generated, `npm run gen:api`; user decision, 2026-10-19), under the
// names the app uses. Where the backend's schema is looser than the contract (a status the
// backend types as `string`), `Narrow` says so, and the compiler checks that the narrowed type
// still fits the generated one. Only what the OpenAPI schema does not describe is written by
// hand here: the problem+json errors (`composition.errors`) and the string aliases below.

/** The backend's OpenAPI schemas, by their backend names. */
export type Schemas = components['schemas'];

/**
 * `Base` with some fields narrowed. Each field must exist in `Base` and fit its type there, so a
 * field renamed or retyped by the backend breaks the build instead of drifting.
 */
export type Narrow<
  Base,
  Fields extends { [K in keyof Fields]: K extends keyof Base ? Base[K] : never },
> = Omit<Base, keyof Fields> & Fields;

/** A hand-narrowed request (a union the schema flattens), checked to fit the generated body. */
export type Fits<Narrowed extends Generated, Generated> = Narrowed;

/** A decimal number as a JSON string ("89006.4625467350"), never a float (CLAUDE.md §2). */
export type Decimal = string;
/** A calendar date, `YYYY-MM-DD`. */
export type IsoDate = string;
/** A time of day, `HH:MM:SS`. */
export type IsoTime = string;
/** An instant with its offset, e.g. `2026-10-16T18:40:00-03:00` or `…Z`. */
export type IsoDateTime = string;

/** A list response (P2). */
export interface ListResponse<T> {
  items: T[];
}

/** A keyset-paginated list (P21): `next_cursor` is `null` on the last page. */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

/** A type alias (not an interface) so it is assignable to the client's query record. */
export type PageQuery = {
  limit?: number;
  cursor?: string;
};

export type InputKind = Schemas['InputKind'];

// RFC 9457 problem+json (OQ-15), answered by the app's own handlers, not in the OpenAPI schema.

export interface FieldError {
  code: ErrorCode;
  message: string;
  field: string | null;
}

export type ErrorCode =
  | 'VALIDATION_ERROR'
  | 'FUTURE_DATE'
  | 'CONTRACT_MATURED'
  | 'NOT_FOUND'
  | 'INVALID_RANGE'
  | 'JOB_NOT_CANCELLABLE';

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  errors?: FieldError[];
}
