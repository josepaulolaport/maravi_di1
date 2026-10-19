import { ApiError } from '@/api/http';

const UNEXPECTED = 'Ocorreu um erro inesperado. Tente novamente.';

/**
 * Splits a failed save into the messages its form shows on its own fields and the rest, shown
 * on the page, so no `errors[].message` is ever dropped (OQ-15): a field error whose field the
 * form does not display is shown with the page errors.
 */
export function formErrors(
  error: unknown,
  shownFields: readonly string[],
): { fields: Record<string, string>; page: string[] } {
  if (error === null || error === undefined) return { fields: {}, page: [] };
  if (!(error instanceof ApiError)) return { fields: {}, page: [UNEXPECTED] };
  // Built from every entry, not `fieldErrors()` (first message per field only): a field may
  // carry several messages, and each one is shown.
  const fields: Record<string, string> = {};
  const page = error.pageErrors();
  for (const { field, message } of error.problem.errors ?? []) {
    if (!field) continue;
    if (!shownFields.includes(field)) page.push(message);
    else fields[field] = fields[field] ? `${fields[field]} ${message}` : message;
  }
  return { fields, page };
}
