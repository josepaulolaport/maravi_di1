import { type BoundFunctions, type queries, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type { LedgerEntry, PortfolioSummary } from '@/api/contract';
import { ledgerEntries, summaries } from '@/test/msw/fixtures';
import { url, type User } from '@/test/helpers';
import { server } from '@/test/msw/server';
import { renderRoute } from '@/test/render';

// Expected figures are the fixtures' values (src/test/msw/fixtures.ts), formatted in pt-BR. Intl puts a no-break space after "R$"; Testing Library's default normalizer turns
// it into a plain space, so expectations use a plain space.

export const FULL_RANGE = '/lancamentos?inicio=2026-10-14&fim=2026-10-16';

export async function openLedger(route = FULL_RANGE) {
  const result = renderRoute(route);
  await screen.findByText(/lançamentos? encontrados?$/);
  return result;
}

export function table() {
  return screen.getByRole('table', { name: 'Lançamentos' });
}

export function bodyRows() {
  return within(table()).getAllByRole('row').slice(1);
}

export function rowNamed(name: string) {
  const checkbox = screen.getByRole('checkbox', { name: `Selecionar ${name}` });
  const row = checkbox.closest('tr');
  if (!row) throw new Error(`no row for ${name}`);
  return within(row);
}

/**
 * Serves the entries in `ledger.items` (newest first) within the requested dates. After a
 * write, a test sets `items` to what the API returns then.
 */
export function serveEntries() {
  const ledger = { items: [...ledgerEntries] };
  server.use(
    http.get(url('/ledger/entries'), ({ request }) => {
      const params = new URL(request.url).searchParams;
      const start = params.get('start_date') ?? '';
      const end = params.get('end_date') ?? '';
      const items = ledger.items.filter((e) => e.date >= start && e.date <= end);
      return HttpResponse.json({ items, next_cursor: null });
    }),
  );
  return ledger;
}

/** Answers a create with `created`, which the list includes from then on. */
export function answerCreate(ledger: { items: LedgerEntry[] }, created: LedgerEntry) {
  server.use(
    http.post(url('/ledger/entries'), () => {
      ledger.items = [created, ...ledger.items];
      return HttpResponse.json(created, { status: 201 });
    }),
  );
}

/** Answers each deletion with 204; the list leaves the deleted entries out from then on. */
export function answerDeletes(ledger: { items: LedgerEntry[] }) {
  server.use(
    http.post(url('/ledger/entries/deletions'), async ({ request }) => {
      const { ids } = (await request.clone().json()) as { ids: string[] };
      ledger.items = ledger.items.filter((e) => !ids.includes(e.id));
      return new HttpResponse(null, { status: 204 });
    }),
  );
}

/**
 * The search is the backend's (§11.3): each searched word gets `answers[word]`; a request
 * without a search falls through. Records the searches sent.
 */
export function serveSearch(answers: Record<string, LedgerEntry[]>) {
  const searches: string[] = [];
  server.use(
    http.get(url('/ledger/entries'), ({ request }) => {
      const search = new URL(request.url).searchParams.get('search');
      if (search === null) return undefined;
      searches.push(search);
      return HttpResponse.json({ items: answers[search] ?? [], next_cursor: null });
    }),
  );
  return searches;
}

export const DI1F28_ENTRIES = ledgerEntries.filter(
  (e) => e.type === 'TRADE' && e.asset_code === 'DI1F28',
);

/** Serves the cash chain of `date` as Erro, its published cash kept (OQ-23). */
export function failCash(date: string) {
  const summary = summaries[date] as PortfolioSummary;
  server.use(
    http.get(url('/portfolio/summary'), ({ request }) =>
      new URL(request.url).searchParams.get('date') === date
        ? HttpResponse.json({ ...summary, cash: { ...summary.cash, status: 'FAILED' } })
        : undefined,
    ),
  );
}

const ENTRY_GROUP = {
  Compra: 'Operação',
  Venda: 'Operação',
  Aporte: 'Caixa',
  Retirada: 'Caixa',
} as const;

/** "Novo lançamento" → the modal, set to the given kind of entry (Operação or Caixa first). */
export async function openNew(user: User, item: keyof typeof ENTRY_GROUP) {
  await user.click(screen.getByRole('button', { name: 'Novo lançamento' }));
  const modal = within(await screen.findByRole('dialog', { name: 'Novo lançamento' }));
  await user.click(modal.getByRole('radio', { name: ENTRY_GROUP[item] }));
  await user.click(modal.getByRole('radio', { name: item }));
  return modal;
}

export async function typeDate(user: User, input: HTMLElement, text: string) {
  await user.clear(input);
  await user.type(input, text);
  await user.tab();
}

export async function chooseContract(
  user: User,
  modal: BoundFunctions<typeof queries>,
  code: string,
) {
  const select = modal.getByRole('combobox', { name: 'Contrato' });
  await waitFor(() => {
    expect(select).toBeEnabled();
  });
  await user.click(select);
  // jsdom never ends Mantine's dropdown transition (the providers do not set env="test"), so
  // the open listbox stays display:none; the option is found including hidden elements.
  await user.click(await screen.findByRole('option', { name: code, hidden: true }));
  expect(select).toHaveValue(code);
}
