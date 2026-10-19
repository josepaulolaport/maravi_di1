import type { IsoDate, IsoTime } from '@/api/contract';
import { ApiError } from '@/api/http';
import { isIsoDate } from '@/shared/format';

/** "16/10/2026" → "2026-10-16" for the date inputs; `null` when it is not a calendar date. */
export function parsePtBrDate(text: string): IsoDate | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(text.trim());
  if (!match) return null;
  const iso = `${match[3] ?? ''}-${match[2] ?? ''}-${match[1] ?? ''}`;
  return isIsoDate(iso) ? iso : null;
}

/** The current São Paulo time as `HH:MM`, the form's suggestion for a trade (OQ-13). */
export function nowInSaoPaulo(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/Sao_Paulo',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(now);
}

/** `HH:MM` from the time input → the API's `HH:MM:SS`. */
export const toIsoTime = (value: string): IsoTime => (value.length === 5 ? `${value}:00` : value);

interface SplitErrors {
  /** Messages keyed by form field. */
  fields: Record<string, string>;
  /** Messages shown above the form: no field, or a field the form does not have. */
  page: string[];
}

/**
 * Splits a failed write (problem+json, OQ-15) into messages on the form's fields, using
 * `fieldMap` (API field → form field), and messages for the top of the form. Every message is
 * kept: two API fields of one input are joined on it; an unknown field goes to the top.
 */
export function splitErrors(error: unknown, fieldMap: Record<string, string>): SplitErrors {
  if (!(error instanceof ApiError)) {
    return { fields: {}, page: ['Ocorreu um erro inesperado. Tente novamente.'] };
  }
  const errors = error.problem.errors ?? [];
  if (errors.length === 0) return { fields: {}, page: [error.message] };
  const fields: Record<string, string> = {};
  const page: string[] = [];
  for (const { field, message } of errors) {
    const formField = field ? fieldMap[field] : undefined;
    if (!formField) page.push(message);
    else fields[formField] = fields[formField] ? `${fields[formField]} ${message}` : message;
  }
  return { fields, page };
}
