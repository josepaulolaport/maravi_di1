import { screen, within } from '@testing-library/react';
import type { UserEvent } from '@testing-library/user-event';
import { HttpResponse } from 'msw';

import type { ErrorCode, FieldError, Problem } from '@/api/contract';
import { API_BASE } from '@/api/http';

// Helpers every screen test shares. Screen-specific ones live in ./screens/<feature>.ts.

/** The user of a rendered screen (`renderRoute(...).user`). */
export type User = UserEvent;

/** Full URL of an API path. */
export const url = (path: string) => `${API_BASE}${path}`;

export const fieldError = (
  code: ErrorCode,
  message: string,
  field: string | null = null,
): FieldError => ({ code, message, field });

/** An RFC 9457 problem+json response (OQ-15). */
export function problem(status: number, errors: FieldError[]) {
  const body: Problem = {
    type: 'about:blank',
    title: 'Erro',
    status,
    detail: errors[0]?.message ?? 'Erro',
    errors,
  };
  return HttpResponse.json(body, {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  });
}

/** The table row with a cell that reads `text` (a date, a code). */
export function rowElement(text: string): HTMLElement {
  const row = screen.getByText(text, { selector: 'td, td *' }).closest('tr');
  if (!row) throw new Error(`no row for ${text}`);
  return row;
}

/** Queries inside the table row with a cell that reads `text`. */
export const rowContaining = (text: string) => within(rowElement(text));

/**
 * The text of each cell of a row. Intl puts a no-break space after "R$"; it is read as a plain
 * space, as Testing Library's default normalizer does, so expectations use a plain space.
 */
export function cellTexts(row: HTMLElement): string[] {
  return within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent.replaceAll(' ', ' '));
}
