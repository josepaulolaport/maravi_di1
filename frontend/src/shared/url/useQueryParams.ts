import { useEffect } from 'react';
import { useSearchParams } from 'react-router';

import type { IsoDate } from '@/api/contract';
import { isIsoDate } from '@/shared/format';
import { useToday } from '@/shared/hooks/useToday';

import { useFutureDateNotice } from './futureDate';

// URL state (frontend/CLAUDE.md): a screen's date, range, tab, search and order live in the
// query string, so a view can be linked and reloaded. Every screen reads and writes them the
// same way: a parser per key, invalid values corrected in the URL with a replace, searches and
// orders written with a replace and range or date changes with a push (Back returns to them).

/** How one query-string key is read and written. */
export interface QueryParam<T> {
  /** The value a URL text stands for, or `null` when the text is invalid. */
  parse: (text: string) => T | null;
  /** The URL text of a value; the value itself by default. A method, so `T` stays covariant. */
  format?(value: T): string;
  /** The value when the key is absent or invalid; an invalid text is replaced by it in the URL. */
  fallback?: T;
  /** A date after today in a link is reported, not silently dropped (OQ-14). */
  refusesFuture?: boolean;
}

type ValueOf<P> = P extends QueryParam<infer T> ? T : never;
type Defs = Record<string, QueryParam<unknown>>;
export type QueryValues<D extends Defs> = {
  [K in keyof D]: D[K] extends { fallback: unknown } ? ValueOf<D[K]> : ValueOf<D[K]> | null;
};
type Changes<D extends Defs> = { [K in keyof D]?: ValueOf<D[K]> | null };

const formatOf = <T>(param: QueryParam<T>, value: T): string =>
  param.format ? param.format(value) : String(value);

/**
 * Reads `defs` from the query string. `refine` may reject values that depend on each other (a
 * start after its end): a rejected value becomes `null` and leaves the URL. Returns the values
 * and `set`, which writes changes (`null` or `''` removes a key) with a replace, or a push.
 */
export function useQueryParams<D extends Defs>(
  defs: D,
  refine?: (values: QueryValues<D>) => Partial<QueryValues<D>>,
) {
  const [params, setParams] = useSearchParams();
  const today = useToday();

  const entries = Object.entries<QueryParam<unknown>>(defs);
  const parsed: Record<string, unknown> = {};
  for (const [key, param] of entries) {
    const text = params.get(key);
    parsed[key] = (text === null ? null : param.parse(text)) ?? param.fallback ?? null;
  }
  const values: Record<string, unknown> = {
    ...parsed,
    ...refine?.(parsed as QueryValues<D>),
  };
  useFutureDateNotice(
    entries.flatMap(([key, param]) => (param.refusesFuture ? [params.get(key)] : [])),
    today,
  );

  const textOf = (param: QueryParam<unknown>, value: unknown) =>
    value === null || value === undefined ? null : formatOf(param, value) || null;

  // What the URL must say instead of what it says: an invalid value, corrected once.
  const fixes: Record<string, string | null> = {};
  for (const [key, param] of entries) {
    const text = params.get(key);
    const wanted = textOf(param, values[key]);
    if (text !== null && wanted !== text) fixes[key] = wanted;
  }
  const pending = JSON.stringify(fixes);
  useEffect(() => {
    const changes = JSON.parse(pending) as Record<string, string | null>;
    if (Object.keys(changes).length === 0) return;
    setParams((current) => apply(current, changes), { replace: true });
  }, [pending, setParams]);

  const set = (changes: Changes<D>, options: { push?: boolean } = {}) => {
    const texts: Record<string, string | null> = {};
    for (const [key, param] of entries) {
      if (key in changes) texts[key] = textOf(param, changes[key]);
    }
    setParams((current) => apply(current, texts), { replace: options.push !== true });
  };

  return { values: values as QueryValues<D>, set };
}

function apply(current: URLSearchParams, changes: Record<string, string | null>) {
  for (const [key, text] of Object.entries(changes)) {
    if (text === null) current.delete(key);
    else current.set(key, text);
  }
  return current;
}

// Parsers.

/** Free text, such as a search; an empty one is absent. */
export const textParam: QueryParam<string> & { fallback: string } = {
  parse: (text) => text || null,
  fallback: '',
};

/** One of a set of values, each with its URL text (`escopo=caixa` is CASH). */
export function enumParam<T extends string>(texts: Record<T, string>): QueryParam<T> {
  const entries = Object.entries(texts) as [T, string][];
  return {
    parse: (text) => entries.find(([, t]) => t === text)?.[0] ?? null,
    format: (value) => texts[value],
  };
}

/**
 * A calendar date `YYYY-MM-DD`. With `max`, a later date is invalid; with `max` set to today
 * (OQ-14), a future date in a link is also reported.
 */
export function dateParam(options: { max?: IsoDate } = {}): QueryParam<IsoDate> {
  const { max } = options;
  return {
    parse: (text) => (isIsoDate(text) && (max === undefined || text <= max) ? text : null),
    refusesFuture: max !== undefined,
  };
}

/** `param`, read as `fallback` when absent or invalid (an invalid text is corrected to it). */
export function withFallback<T>(
  param: QueryParam<T>,
  fallback: T,
): QueryParam<T> & { fallback: T } {
  return { ...param, fallback };
}
