import { delay, HttpResponse } from 'msw';

import type { ErrorCode, FieldError, Page, Problem } from '../../contract';
import { API_BASE } from '../../http';
import { isIsoDate, today } from '../dates';
import { db } from '../db';

/** Full mock URL for an API path. */
export const url = (path: string) => `${API_BASE}${path}`;

/** A short realistic latency in the browser; none in Node (tests). */
export const latency = () => delay();

const TITLES: Record<number, string> = {
  404: 'Recurso não encontrado',
  409: 'Conflito',
  422: 'Dados inválidos',
};

export function problem(status: number, errors: FieldError[]) {
  const body: Problem = {
    type: 'about:blank',
    title: TITLES[status] ?? 'Erro',
    status,
    detail: errors[0]?.message ?? 'Erro',
    errors,
  };
  return HttpResponse.json(body, {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  });
}

export const fieldError = (code: ErrorCode, message: string, field: string | null = null) => ({
  code,
  message,
  field,
});

export const notFound = (what: string) =>
  problem(404, [fieldError('NOT_FOUND', `${what} não encontrado.`)]);

/** Errors for a date that must be a valid calendar date not after today (OQ-14). */
export function dateErrors(value: unknown, field: string): FieldError[] {
  if (!isIsoDate(value)) return [fieldError('VALIDATION_ERROR', 'Informe uma data válida.', field)];
  if (value > today()) {
    return [fieldError('FUTURE_DATE', 'A data não pode ser posterior a hoje.', field)];
  }
  return [];
}

const DECIMAL = /^-?\d+(\.\d+)?$/;

/** Errors for a typed decimal: format, the schema bound, and the OQ-3 decimal places. */
export function decimalErrors(
  value: unknown,
  field: string,
  maxPlaces: number,
  bound: 'positive' | 'rate',
): FieldError[] {
  if (typeof value !== 'string' || !DECIMAL.test(value)) {
    return [fieldError('VALIDATION_ERROR', 'Informe um número válido.', field)];
  }
  const places = value.split('.')[1]?.length ?? 0;
  if (places > maxPlaces) {
    return [fieldError('VALIDATION_ERROR', `Use no máximo ${maxPlaces} casas decimais.`, field)];
  }
  const negative = value.startsWith('-');
  const zero = /^-?0+(\.0+)?$/.test(value);
  if (bound === 'positive' && (negative || zero)) {
    return [fieldError('VALIDATION_ERROR', 'O valor deve ser maior que zero.', field)];
  }
  if (bound === 'rate' && negative && !/^-0(\.\d+)?$/.test(value)) {
    return [fieldError('VALIDATION_ERROR', 'A taxa deve ser maior que −100%.', field)];
  }
  return [];
}

export function findInstrument(assetId: unknown) {
  return db.instruments.find((i) => i.id === assetId);
}

/**
 * FAKE pricing for the mock backend only: converts the typed PU or rate with DC/365 in
 * binary floating point. Its last digits are approximate; the real backend computes them in
 * Decimal (OQ-3). Never import this outside the mocks.
 */
export function fakePricing(
  inputKind: 'PU' | 'RATE',
  value: string,
  calendarDays: number,
): { pu: string; rate: string } {
  if (calendarDays === 0) return { pu: value, rate: '0' };
  const years = calendarDays / 365;
  if (inputKind === 'RATE') {
    return { pu: (100000 / (1 + Number(value)) ** years).toFixed(10), rate: value };
  }
  return { pu: value, rate: ((100000 / Number(value)) ** (1 / years) - 1).toFixed(12) };
}

/** Case-insensitive search without accents, for the mock filters. */
export function matches(haystack: (string | null | undefined)[], search: string | null): boolean {
  if (!search) return true;
  const normalize = (s: string) =>
    s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLocaleLowerCase('pt-BR');
  const needle = normalize(search.trim());
  return haystack.some((value) => value && normalize(value).includes(needle));
}

export async function readJson(request: Request): Promise<Record<string, unknown>> {
  try {
    const body: unknown = await request.json();
    return typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export function rangeErrors(start: unknown, end: unknown): FieldError[] {
  const errors = [...dateErrors(start, 'start_date'), ...dateErrors(end, 'end_date')];
  if (errors.length === 0 && (start as string) > (end as string)) {
    errors.push(
      fieldError(
        'INVALID_RANGE',
        'A data inicial deve ser anterior ou igual à data final.',
        'start_date',
      ),
    );
  }
  return errors;
}

/** The page size when `limit` is not given, and the largest one accepted. */
const DEFAULT_PAGE_SIZE = 50;
const MAX_PAGE_SIZE = 200;

/**
 * Keyset pagination over an already-ordered list (P21): the cursor is opaque to the client;
 * here it carries the id of the last row of the previous page. Returns the problem response
 * for an invalid `limit` or an unknown cursor.
 */
export function paginate<T extends { id: string }>(
  ordered: T[],
  request: Request,
): Page<T> | Response {
  const params = new URL(request.url).searchParams;
  const rawLimit = params.get('limit');
  const limit = rawLimit === null ? DEFAULT_PAGE_SIZE : Number(rawLimit);
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_PAGE_SIZE) {
    return problem(422, [
      fieldError('VALIDATION_ERROR', `Use um limite entre 1 e ${MAX_PAGE_SIZE}.`, 'limit'),
    ]);
  }
  const cursor = params.get('cursor');
  let from = 0;
  if (cursor !== null) {
    const index = ordered.findIndex((row) => row.id === atob(cursor));
    if (index < 0) {
      return problem(422, [fieldError('VALIDATION_ERROR', 'Cursor inválido.', 'cursor')]);
    }
    from = index + 1;
  }
  const items = ordered.slice(from, from + limit);
  const last = items.at(-1);
  const more = from + limit < ordered.length;
  return { items, next_cursor: more && last ? btoa(last.id) : null };
}
