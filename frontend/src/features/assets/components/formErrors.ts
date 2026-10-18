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
  const fields = error.fieldErrors();
  const orphans = Object.entries(fields)
    .filter(([field]) => !shownFields.includes(field))
    .map(([, message]) => message);
  return { fields, page: [...error.pageErrors(), ...orphans] };
}
