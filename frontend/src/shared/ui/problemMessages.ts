import { ApiError } from '@/api/http';

const UNEXPECTED = 'Ocorreu um erro inesperado. Tente novamente.';

/**
 * The pt-BR messages of a failed request (RFC 9457 problem+json, OQ-15), all of them, for a
 * read or a dialog that has no fields to show them on.
 */
export function problemMessages(error: unknown): string[] {
  return splitProblem(error, {}).page;
}

/**
 * Splits a failed save into the messages a form shows on its own fields and the rest, shown
 * above the form (OQ-15). `fieldMap` maps an API field to the form field that shows it; every
 * message is kept: several messages for one input are joined on it, and a field the form does
 * not show goes with the page messages.
 */
export function splitProblem(
  error: unknown,
  fieldMap: Readonly<Record<string, string>>,
): { fields: Record<string, string>; page: string[] } {
  if (error === undefined || error === null) return { fields: {}, page: [] };
  if (!(error instanceof ApiError)) return { fields: {}, page: [UNEXPECTED] };
  const errors = error.problem.errors ?? [];
  if (errors.length === 0) return { fields: {}, page: [error.message] };
  const fields: Record<string, string> = {};
  const page: string[] = [];
  for (const { field, message } of errors) {
    const formField = field && Object.hasOwn(fieldMap, field) ? fieldMap[field] : undefined;
    if (!formField) page.push(message);
    else fields[formField] = fields[formField] ? `${fields[formField]} ${message}` : message;
  }
  return { fields, page };
}
