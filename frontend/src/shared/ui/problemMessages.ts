import { ApiError } from '@/api/http';

/**
 * The pt-BR messages of a failed request (RFC 9457 problem+json, OQ-15), for a modal. A form that shows a field's message on its own input (the first one, as
 * `ApiError.fieldErrors()` keeps) names that field in `shownOnFields`; that message is left
 * out here, and any further message for the field stays, so none is lost.
 */
export function problemMessages(error: unknown, shownOnFields: readonly string[] = []): string[] {
  if (error === undefined || error === null) return [];
  if (!(error instanceof ApiError)) return ['Ocorreu um erro inesperado. Tente novamente.'];
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
