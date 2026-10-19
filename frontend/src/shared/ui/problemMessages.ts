import { ApiError } from '@/api/http';

const UNEXPECTED = 'Ocorreu um erro inesperado. Tente novamente.';

/**
 * The pt-BR messages of a failed request (RFC 9457 problem+json, OQ-15), for a modal. A form
 * that shows a field's message on its own input (the first one, as
 * `ApiError.fieldErrors()` keeps) names that field in `shownOnFields`; that message is left
 * out here, and any further message for the field stays, so none is lost.
 */
export function problemMessages(error: unknown, shownOnFields: readonly string[] = []): string[] {
  if (error === undefined || error === null) return [];
  if (!(error instanceof ApiError)) return [UNEXPECTED];
  const errors = error.problem.errors ?? [];
  if (errors.length === 0) return [error.message];
  const shown = new Set<string>();
  return errors
    .filter((e) => {
      if (e.field === null || !shownOnFields.includes(e.field) || shown.has(e.field)) return true;
      shown.add(e.field);
      return false;
    })
    .map((e) => e.message);
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
    const formField = field ? fieldMap[field] : undefined;
    if (!formField) page.push(message);
    else fields[formField] = fields[formField] ? `${fields[formField]} ${message}` : message;
  }
  return { fields, page };
}
