import {
  type BoundFunctions,
  fireEvent,
  type queries,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import type { LedgerEntry, PortfolioSummary } from '@/api/contract';
import {
  cashEntries,
  IDS,
  instruments,
  ledgerEntries,
  preview,
  products,
  summaries,
  tradeEntries,
} from '@/test/msw/fixtures';
import { fieldError, problem, url } from '@/test/msw/handlers';
import { captureBodies, server } from '@/test/msw/server';
import { addDays, formatDate, todayInSaoPaulo } from '@/shared/format';
import { renderApp } from '@/test/render';

// Expected figures are the fixtures' values (src/test/msw/fixtures.ts), formatted in pt-BR. Intl puts a no-break space after "R$"; Testing Library's default normalizer turns
// it into a plain space, so expectations use a plain space.

const FULL_RANGE = '/lancamentos?inicio=2026-10-14&fim=2026-10-16';

async function openLedger(route = FULL_RANGE) {
  const result = renderApp(route);
  await screen.findByText(/lançamentos? encontrados?$/);
  return result;
}

function table() {
  return screen.getByRole('table', { name: 'Lançamentos' });
}

function bodyRows() {
  return within(table()).getAllByRole('row').slice(1);
}

function rowNamed(name: string) {
  const checkbox = screen.getByRole('checkbox', { name: `Selecionar ${name}` });
  const row = checkbox.closest('tr');
  if (!row) throw new Error(`no row for ${name}`);
  return within(row);
}

function cellTexts(row: HTMLElement) {
  return within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent.replaceAll('\u00a0', ' '));
}

/**
 * Serves the entries in `ledger.items` (newest first) within the requested dates. After a
 * write, a test sets `items` to what the API returns then.
 */
function serveEntries() {
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
function answerCreate(ledger: { items: LedgerEntry[] }, created: LedgerEntry) {
  server.use(
    http.post(url('/ledger/entries'), () => {
      ledger.items = [created, ...ledger.items];
      return HttpResponse.json(created, { status: 201 });
    }),
  );
}

/** Answers each deletion with 204; the list leaves the deleted entries out from then on. */
function answerDeletes(ledger: { items: LedgerEntry[] }) {
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
function serveSearch(answers: Record<string, LedgerEntry[]>) {
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

const DI1F28_ENTRIES = ledgerEntries.filter((e) => e.type === 'TRADE' && e.asset_code === 'DI1F28');

/** Serves the cash chain of `date` as Erro, its published cash kept (OQ-23). */
function failCash(date: string) {
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
async function openNew(user: ReturnType<typeof renderApp>['user'], item: keyof typeof ENTRY_GROUP) {
  await user.click(screen.getByRole('button', { name: 'Novo lançamento' }));
  const modal = within(await screen.findByRole('dialog', { name: 'Novo lançamento' }));
  await user.click(modal.getByRole('radio', { name: ENTRY_GROUP[item] }));
  await user.click(modal.getByRole('radio', { name: item }));
  return modal;
}

async function typeDate(
  user: ReturnType<typeof renderApp>['user'],
  input: HTMLElement,
  text: string,
) {
  await user.clear(input);
  await user.type(input, text);
  await user.tab();
}

async function chooseContract(
  user: ReturnType<typeof renderApp>['user'],
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

// The notifications store is module-global: without this, earlier tests fill its limit and
// a later notification waits in the queue instead of showing.
afterEach(() => {
  notifications.clean();
});

describe('Lançamentos (§11.3)', () => {
  describe('list', () => {
    it('§11.3 shows a loading state, then the entries', async () => {
      renderApp(FULL_RANGE);

      expect(await screen.findByLabelText('Carregando lançamentos')).toBeInTheDocument();
      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§11.3 has separate columns for instrument type and entry type', async () => {
      await openLedger();

      const headers = within(table())
        .getAllByRole('columnheader')
        .map((h) => h.textContent);
      expect(headers).toEqual([
        '',
        'Data e hora',
        'Tipo de ativo',
        'Tipo',
        'Ativo',
        'Qtd.',
        'PU',
        'Taxa',
        'Valor financeiro',
        'Ações',
      ]);
    });

    it('§11.3 lists trades and cash entries in one order, newest first, in pt-BR formats', async () => {
      await openLedger();
      await screen.findAllByText('Futuros');

      expect(bodyRows().map(cellTexts)).toEqual([
        ['', '16/10/2026 17:30', 'Caixa', 'Retirada', '—', '—', '—', '—', '-R$ 50.000,00', ''],
        [
          '',
          '16/10/2026 15:00',
          'Futuros',
          'Venda',
          'DI1F28',
          '-4',
          '89.102,22',
          '9,9500%',
          '+R$ 356.408,89',
          '',
        ],
        [
          '',
          '15/10/2026 10:30',
          'Futuros',
          'Compra',
          'DI1F29',
          '+5',
          '82.057,00',
          '9,3203%',
          '-R$ 410.285,00',
          '',
        ],
        [
          '',
          '14/10/2026 14:10',
          'Futuros',
          'Compra',
          'DI1F28',
          '+10',
          '89.006,46',
          '10,0000%',
          '-R$ 890.064,63',
          '',
        ],
        ['', '14/10/2026 09:00', 'Caixa', 'Aporte', '—', '—', '—', '—', '+R$ 1.500.000,00', ''],
      ]);
    });

    it('§11.3 sorts by Data e hora, descending by default, ascending on click', async () => {
      const orders: (string | null)[] = [];
      server.use(
        http.get(url('/ledger/entries'), ({ request }) => {
          const order = new URL(request.url).searchParams.get('order');
          orders.push(order);
          // The API's ascending answer: the same entries, oldest first.
          const items = order === 'asc' ? [...ledgerEntries].reverse() : ledgerEntries;
          return HttpResponse.json({ items, next_cursor: null });
        }),
      );
      const { user, router } = await openLedger();
      const header = screen.getByRole('columnheader', { name: 'Data e hora' });
      expect(header).toHaveAttribute('aria-sort', 'descending');

      await user.click(within(header).getByRole('button'));

      expect(header).toHaveAttribute('aria-sort', 'ascending');
      // The order is in the URL, so the view can be linked (`?ordem=asc`).
      expect(router.state.location.search).toContain('ordem=asc');
      // The order is the backend's: the screen asks for it, it never sorts the rows itself.
      await waitFor(() => {
        expect(orders).toEqual(['desc', 'asc']);
      });
      await waitFor(() => {
        expect(cellTexts(bodyRows()[0] as HTMLElement)[1]).toBe('14/10/2026 09:00');
      });
      expect(cellTexts(bodyRows()[4] as HTMLElement)[1]).toBe('16/10/2026 17:30');
    });

    it('§11.3 a new range shows the loading state, never the rows of the previous range', async () => {
      let release: () => void = () => undefined;
      const { router } = await openLedger();
      server.use(
        http.get(url('/ledger/entries'), async () => {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return undefined;
        }),
      );

      await router.navigate('/lancamentos?inicio=2026-10-01&fim=2026-10-05');

      expect(await screen.findByLabelText('Carregando lançamentos')).toBeInTheDocument();
      expect(screen.queryByText('5 lançamentos encontrados')).not.toBeInTheDocument();
      release();
    });

    it('§11.3 the range is inclusive on both ends', async () => {
      await openLedger('/lancamentos?inicio=2026-10-15&fim=2026-10-16');

      expect(screen.getByText('3 lançamentos encontrados')).toBeInTheDocument();
      expect(bodyRows().map((row) => cellTexts(row)[1])).toEqual([
        '16/10/2026 17:30',
        '16/10/2026 15:00',
        '15/10/2026 10:30',
      ]);
    });

    it('§11.3 a one-day range keeps the entries of that day', async () => {
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-14');

      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§11.3 searches by asset from the URL (busca)', async () => {
      const searches = serveSearch({ DI1F28: DI1F28_ENTRIES });
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-16&busca=DI1F28');

      expect(screen.getByRole('textbox', { name: 'Buscar' })).toHaveValue('DI1F28');
      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();
      expect(bodyRows().map((row) => cellTexts(row)[4])).toEqual(['DI1F28', 'DI1F28']);
      expect(searches).toEqual(['DI1F28']);
    });

    it('§11.3 typing a search filters the list and keeps it in the URL', async () => {
      const searches = serveSearch({ retirada: [cashEntries[1] as LedgerEntry] });
      const { user, router } = await openLedger();

      await user.type(screen.getByRole('textbox', { name: 'Buscar' }), 'retirada');

      expect(await screen.findByText('1 lançamento encontrado')).toBeInTheDocument();
      expect(router.state.location.search).toContain('busca=retirada');
      expect(cellTexts(bodyRows()[0] as HTMLElement)[3]).toBe('Retirada');
      expect(searches.at(-1)).toBe('retirada');
    });

    it('§11.3 without inicio/fim, lists the 30 days ending today (São Paulo)', async () => {
      const today = todayInSaoPaulo();
      const start = addDays(today, -29);
      const seen: string[] = [];
      server.use(
        http.get(url('/ledger/entries'), ({ request }) => {
          seen.push(new URL(request.url).search);
          return HttpResponse.json({ items: [], next_cursor: null });
        }),
      );

      await openLedger('/lancamentos?busca=DI1F29');

      expect(seen[0]).toBe(
        `?start_date=${start}&end_date=${today}&search=DI1F29&order=desc&limit=50`,
      );
      expect(screen.getByRole('button', { name: 'Período' })).toHaveTextContent(
        `${formatDate(start)} – ${formatDate(today)}`,
      );
    });

    it('P21 reads the list page by page: "Carregar mais" asks for the next cursor', async () => {
      const seen: (string | null)[] = [];
      server.use(
        http.get(url('/ledger/entries'), ({ request }) => {
          const cursor = new URL(request.url).searchParams.get('cursor');
          seen.push(cursor);
          return cursor === 'page-2'
            ? HttpResponse.json({ items: tradeEntries.slice(0, 2), next_cursor: null })
            : HttpResponse.json({ items: cashEntries, next_cursor: 'page-2' });
        }),
      );
      const { user } = renderApp(FULL_RANGE);

      expect(await screen.findByText('2 lançamentos exibidos')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Carregar mais' }));

      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Carregar mais' })).not.toBeInTheDocument();
      expect(seen.slice(0, 2)).toEqual([null, 'page-2']);
    });

    it('§11.3 shows the empty state for a range without entries', async () => {
      await openLedger('/lancamentos?inicio=2026-10-01&fim=2026-10-05');

      expect(screen.getByText('0 lançamentos encontrados')).toBeInTheDocument();
      expect(screen.getByText('Nenhum lançamento no período.')).toBeInTheDocument();
    });

    it('§12 shows the API error with a retry', async () => {
      server.use(
        http.get(url('/ledger/entries'), () =>
          problem(422, [fieldError('INVALID_RANGE', 'Período inválido para a consulta.', null)]),
        ),
      );
      const { user } = renderApp(FULL_RANGE);

      expect(await screen.findByText('Período inválido para a consulta.')).toBeInTheDocument();
      server.resetHandlers();
      await user.click(screen.getByRole('button', { name: 'Tentar novamente' }));
      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§11.3 never shows an instrument type code: unavailable until the API names it', async () => {
      server.use(
        http.get(url('/instrument-types'), () =>
          problem(404, [fieldError('NOT_FOUND', 'Tipos não encontrados.')]),
        ),
      );
      await openLedger();

      expect(screen.queryByText('FUTURE')).not.toBeInTheDocument();
      // Row 1 is the 16/10 venda (row 0 is the 17:30 retirada, whose type is always Caixa).
      expect(cellTexts(bodyRows()[1] as HTMLElement)[2]).toBe('—');
    });

    it('§11.3 clearing busca in the URL clears the search box and keeps it cleared', async () => {
      serveSearch({ DI1F28: DI1F28_ENTRIES });
      const { router } = await openLedger(`${FULL_RANGE}&busca=DI1F28`);
      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();

      await router.navigate(FULL_RANGE);

      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: 'Buscar' })).toHaveValue('');
      await new Promise((resolve) => setTimeout(resolve, 400));
      expect(router.state.location.search).not.toContain('busca');
    });
  });

  describe('future dates in the link (OQ-14)', () => {
    it('OQ-14 says a future end date in the link was ignored', async () => {
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2099-01-01');

      expect(
        await screen.findByText('A data 01/01/2099 não pode ser posterior a hoje e foi ignorada.'),
      ).toBeInTheDocument();
    });
  });

  describe('cash strip (OQ-19 item 3)', () => {
    it('§11.3 OQ-21 shows the published cash of the range end and the day before, with its processing time', async () => {
      await openLedger();

      const before = within(screen.getByRole('group', { name: 'Caixa D−1' }));
      const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
      expect(before.getByText('15/10/2026')).toBeInTheDocument();
      expect(await before.findByText('R$ 199.650,37')).toBeInTheDocument();
      expect(end.getByText('16/10/2026')).toBeInTheDocument();
      expect(await end.findByText('R$ 506.059,27')).toBeInTheDocument();
      // A processed date carries no badge, only its processing time (OQ-31).
      for (const group of [before, end]) {
        expect(group.getByText('Processado em 16/10/2026 18:40')).toBeInTheDocument();
        expect(group.queryByText(/^(Processado|Erro|Não processado)$/)).not.toBeInTheDocument();
      }
      expect(screen.queryByRole('button', { name: 'Processar caixa' })).not.toBeInTheDocument();
    });

    it('OQ-23 "Processar caixa" from a failed Caixa D−1 covers D−1 to D0, scope Caixa', async () => {
      failCash('2026-10-15');
      const { user } = await openLedger();

      await user.click(await screen.findByRole('button', { name: 'Processar caixa' }));

      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
      expect(modal.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('15/10/2026');
      expect(modal.getByRole('textbox', { name: 'Data final' })).toHaveValue('16/10/2026');
      expect(modal.getByRole('radio', { name: 'Caixa' })).toBeChecked();
    });

    it('OQ-23 a failed cash date keeps its published cash, reads "Erro" and offers "Processar caixa"', async () => {
      failCash('2026-10-16');
      await openLedger();

      const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
      expect(await end.findByText('R$ 506.059,27')).toBeInTheDocument();
      expect(end.getByText('Erro')).toBeInTheDocument();
      expect(await screen.findByRole('button', { name: 'Processar caixa' })).toBeInTheDocument();
    });

    it('§11.3 shows unprocessed dates as unavailable, never as zero', async () => {
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-18');

      for (const [label, date] of [
        ['Caixa D−1', '17/10/2026'],
        ['Caixa D0', '18/10/2026'],
      ] as const) {
        const group = within(screen.getByRole('group', { name: label }));
        expect(group.getByText(date)).toBeInTheDocument();
        expect(await group.findByText('Não processado')).toBeInTheDocument();
        expect(group.getByText('—')).toBeInTheDocument();
      }
    });
  });

  it('§11.3 marks a load failure of the strip as unavailable', async () => {
    server.use(
      http.get(url('/portfolio/summary'), () =>
        problem(422, [fieldError('VALIDATION_ERROR', 'Data inválida.', 'date')]),
      ),
    );
    await openLedger();

    const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
    expect(await end.findByText('Erro ao carregar')).toBeInTheDocument();
    expect(end.getByText('—')).toBeInTheDocument();
  });

  it('OQ-31 a write keeps the strip as processed: the figure stays until reprocessed', async () => {
    const { user } = await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-15');
    const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
    expect(await end.findByText('R$ 199.650,37')).toBeInTheDocument();

    const modal = await openNew(user, 'Aporte');
    await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '15/10/2026');
    await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '100,00');
    await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

    await waitFor(() => {
      expect(modal.queryByRole('button', { name: 'Registrar aporte' })).not.toBeInTheDocument();
    });
    expect(end.getByText('R$ 199.650,37')).toBeInTheDocument();
    expect(end.queryByText(/^(Erro|Não processado)$/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Processar caixa' })).not.toBeInTheDocument();
  });

  describe('Compra / Venda (§6.1)', () => {
    it('§6.1 registers a compra typed as PU, positive quantity', async () => {
      answerCreate(serveEntries(), {
        ...(tradeEntries[1] as LedgerEntry),
        id: '9a000001-0000-4000-8000-000000000001',
        date: '2026-10-16',
        time: '16:45:00',
        seq: 6,
      });
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F29');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      fireEvent.change(modal.getByLabelText('Hora', { exact: false }), {
        target: { value: '16:45' },
      });
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '3');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '80.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(
        await screen.findByText(
          /^Compra registrada\. Caixa e posições precisam ser processados a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Tudo\.$/,
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([
        {
          type: 'TRADE',
          asset_id: IDS.di1f29,
          date: '2026-10-16',
          time: '16:45:00',
          signed_quantity: 3,
          input_kind: 'PU',
          execution_pu: '80000.00',
        },
      ]);
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
      expect(await screen.findByText('6 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§6.1 registers a venda typed as a rate, sent as a fraction with a negative quantity', async () => {
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Venda');

      await chooseContract(user, modal, 'DI1F28');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      fireEvent.change(modal.getByLabelText('Hora', { exact: false }), {
        target: { value: '17:05' },
      });
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '2');
      await user.click(modal.getByRole('radio', { name: 'Taxa a.a.' }));
      await user.type(modal.getByRole('textbox', { name: 'Taxa a.a. (%)' }), '10,45');
      await user.click(modal.getByRole('button', { name: 'Registrar venda' }));

      expect(
        await screen.findByText(
          /^Venda registrada\. Caixa e posições precisam ser processados a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Tudo\.$/,
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([
        {
          type: 'TRADE',
          asset_id: IDS.di1f28,
          date: '2026-10-16',
          time: '17:05:00',
          signed_quantity: -2,
          input_kind: 'RATE',
          execution_rate: '0.1045',
        },
      ]);
    });

    it('OQ-13 suggests today and the current time, and has no PU/rate preview', async () => {
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      expect(modal.getByRole('textbox', { name: 'Data' })).toHaveValue(
        formatDate(todayInSaoPaulo()),
      );
      expect(modal.getByLabelText<HTMLInputElement>('Hora', { exact: false }).value).toMatch(
        /^\d{2}:\d{2}$/,
      );
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '89.006,46');
      expect(modal.queryByRole('textbox', { name: 'Taxa a.a. (%)' })).not.toBeInTheDocument();
      expect(modal.queryByText(/%$/)).not.toBeInTheDocument();
    });

    it('OQ-15 keeps the modal open while saving, so the result is never lost', async () => {
      let release: () => void = () => undefined;
      server.use(
        http.post(url('/ledger/entries'), async () => {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return undefined;
        }),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');
      await chooseContract(user, modal, 'DI1F29');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '80.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      await user.keyboard('{Escape}');
      // Past the modal's close transition: a closing modal would be gone by now.
      await new Promise((resolve) => setTimeout(resolve, 400));
      expect(modal.queryByRole('button', { name: 'Fechar' })).not.toBeInTheDocument();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(modal.getByRole('button', { name: 'Registrar compra' })).toBeInTheDocument();
      release();
      expect(
        await screen.findByText(
          /^Compra registrada\. Caixa e posições precisam ser processados a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Tudo\.$/,
        ),
      ).toBeInTheDocument();
    });

    it('§6.1 checks the required fields before sending', async () => {
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(modal.getByText('Selecione um contrato.')).toBeInTheDocument();
      expect(modal.getByText('Informe uma quantidade inteira maior que zero.')).toBeInTheDocument();
      expect(modal.getByText('Informe o PU.')).toBeInTheDocument();
      expect(bodies).toEqual([]);
    });

    it('OQ-3 shows the decimal-place error of a PU on its field', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Use no máximo 10 casas decimais.', 'execution_pu'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F29');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '80.000,12345678901');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByText('Use no máximo 10 casas decimais.')).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'PU' })).toHaveAttribute('aria-invalid', 'true');
    });

    it('OQ-3 shows the decimal-place error of a rate on its field', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Use no máximo 12 casas decimais.', 'execution_rate'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F29');
      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.click(modal.getByRole('radio', { name: 'Taxa a.a.' }));
      // 10,12345678901% = 0.1012345678901: 13 places, one more than OQ-3 allows.
      await user.type(modal.getByRole('textbox', { name: 'Taxa a.a. (%)' }), '10,12345678901');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByText('Use no máximo 12 casas decimais.')).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'Taxa a.a. (%)' })).toHaveAttribute(
        'aria-invalid',
        'true',
      );
    });

    it.each(['Compra', 'Aporte'] as const)(
      'OQ-14 refuses a typed future date in %s on the Data field, never replacing it silently',
      async (kind) => {
        const bodies = captureBodies('/ledger/entries');
        const { user } = await openLedger();
        const modal = await openNew(user, kind);

        const date = modal.getByRole('textbox', { name: 'Data' });
        await typeDate(user, date, '19/10/2026');

        expect(await modal.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
        expect(date).toHaveAttribute('aria-invalid', 'true');
        // The refused date is not kept as some other date that could be saved unnoticed.
        expect(date).not.toHaveValue('18/10/2026');
        await user.click(modal.getByRole('button', { name: /^Registrar/ }));
        expect(bodies).toEqual([]);

        await typeDate(user, date, '17/10/2026');
        expect(modal.queryByText('A data não pode ser posterior a hoje.')).not.toBeInTheDocument();
      },
    );

    it.each([
      ['FUTURE_DATE', 'A data não pode ser posterior a hoje.'],
      ['CONTRACT_MATURED', 'O contrato já venceu nesta data.'],
    ] as const)('OQ-14 / OQ-1 shows %s on the Data field', async (code, message) => {
      server.use(
        http.post(url('/ledger/entries'), () => problem(422, [fieldError(code, message, 'date')])),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F27');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByText(message)).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'Data' })).toHaveAttribute('aria-invalid', 'true');
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('OQ-15 shows every message when two API fields belong to the same input', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Informe um número válido.', 'execution_rate'),
            fieldError('VALIDATION_ERROR', 'Informe o PU ou a taxa.', 'input_kind'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F27');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByText(/Informe um número válido\./)).toBeInTheDocument();
      expect(modal.getByText(/Informe o PU ou a taxa\./)).toBeInTheDocument();
    });

    it('OQ-15 shows an error without a field above the form', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(409, [fieldError('VALIDATION_ERROR', 'Lançamentos bloqueados no momento.')]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      await chooseContract(user, modal, 'DI1F27');
      await user.type(modal.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(modal.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar compra' }));

      expect(await modal.findByRole('alert')).toHaveTextContent(
        'Lançamentos bloqueados no momento.',
      );
    });
  });

  describe('Aporte / Retirada (§6.2)', () => {
    it('§6.2 registers an aporte with its time and a positive amount', async () => {
      answerCreate(serveEntries(), {
        type: 'CASH',
        id: '9a000001-0000-4000-8000-000000000001',
        date: '2026-10-15',
        time: '11:20:00',
        seq: 6,
        cash_amount: '2500.50',
        created_at: '2026-10-18T12:00:00-03:00',
      });
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      fireEvent.change(modal.getByLabelText('Hora', { exact: false }), {
        target: { value: '11:20' },
      });
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '2.500,50');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      expect(
        await screen.findByText(
          /^Aporte registrado\. O caixa precisa ser processado a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Caixa\.$/,
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([
        { type: 'CASH', date: '2026-10-15', time: '11:20:00', cash_amount: '2500.50' },
      ]);
      expect(await screen.findByText('+R$ 2.500,50')).toBeInTheDocument();
    });

    it('§6.2 registers a retirada: typed positive, sent as a negative amount', async () => {
      answerCreate(serveEntries(), {
        type: 'CASH',
        id: '9a000001-0000-4000-8000-000000000001',
        date: '2026-10-15',
        time: '09:05:00',
        seq: 6,
        cash_amount: '-1000',
        created_at: '2026-10-18T12:00:00-03:00',
      });
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Retirada');

      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      fireEvent.change(modal.getByLabelText('Hora', { exact: false }), {
        target: { value: '09:05' },
      });
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '1.000');
      await user.click(modal.getByRole('button', { name: 'Registrar retirada' }));

      expect(
        await screen.findByText(
          /^Retirada registrada\. O caixa precisa ser processado a partir de \d{2}\/\d{2}\/\d{4}: use o escopo Caixa\.$/,
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([
        { type: 'CASH', date: '2026-10-15', time: '09:05:00', cash_amount: '-1000' },
      ]);
      expect(await screen.findByText('-R$ 1.000,00')).toBeInTheDocument();
    });

    it('§6.2 never sends a negative or zero amount: the side gives the sign', async () => {
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '-1.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));
      expect(modal.getByText('Informe um valor maior que zero.')).toBeInTheDocument();

      await user.clear(modal.getByRole('textbox', { name: 'Valor (R$)' }));
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '0,00');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));
      expect(modal.getByText('Informe um valor maior que zero.')).toBeInTheDocument();
      expect(bodies).toEqual([]);
    });

    it('OQ-3 shows the decimal-place error of an amount on its field', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Use no máximo 2 casas decimais.', 'cash_amount'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await typeDate(user, modal.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '10,505');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      expect(await modal.findByText('Use no máximo 2 casas decimais.')).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'Valor (R$)' })).toHaveAttribute(
        'aria-invalid',
        'true',
      );
    });

    it('OQ-14 shows FUTURE_DATE on the Data field', async () => {
      server.use(
        http.post(url('/ledger/entries'), () =>
          problem(422, [
            fieldError('FUTURE_DATE', 'A data não pode ser posterior a hoje.', 'date'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '100,00');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      expect(await modal.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
      expect(modal.getByRole('textbox', { name: 'Data' })).toHaveAttribute('aria-invalid', 'true');
    });

    it('§6.2 rejects a value that is not a pt-BR number before sending', async () => {
      const bodies = captureBodies('/ledger/entries');
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');

      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '1,000.50');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      expect(modal.getByText('Informe um valor válido, como 1.234,56.')).toBeInTheDocument();
      expect(bodies).toEqual([]);
    });
  });

  describe('Novo lançamento modal (§11.3)', () => {
    it('§11.3 opens one modal that switches between Operação and Caixa', async () => {
      const { user } = await openLedger();

      await user.click(screen.getByRole('button', { name: 'Novo lançamento' }));
      const modal = within(await screen.findByRole('dialog', { name: 'Novo lançamento' }));

      expect(screen.queryByRole('menuitem')).not.toBeInTheDocument();
      expect(modal.getByRole('radio', { name: 'Operação' })).toBeChecked();
      expect(modal.getByRole('radio', { name: 'Compra' })).toBeChecked();
      expect(modal.getByRole('radio', { name: 'Venda' })).not.toBeChecked();
      expect(modal.getByRole('combobox', { name: 'Contrato' })).toBeInTheDocument();
      expect(modal.getByRole('button', { name: 'Registrar compra' })).toBeInTheDocument();

      await user.click(modal.getByRole('radio', { name: 'Caixa' }));

      expect(modal.getByRole('radio', { name: 'Aporte' })).toBeChecked();
      expect(modal.getByRole('radio', { name: 'Retirada' })).not.toBeChecked();
      expect(modal.getByRole('textbox', { name: 'Valor (R$)' })).toBeInTheDocument();
      expect(modal.queryByRole('combobox', { name: 'Contrato' })).not.toBeInTheDocument();
      expect(modal.getByRole('button', { name: 'Registrar aporte' })).toBeInTheDocument();

      await user.click(modal.getByRole('radio', { name: 'Retirada' }));
      expect(modal.getByRole('button', { name: 'Registrar retirada' })).toBeInTheDocument();
    });

    it('§11.3 filters the contracts by asset class and finds one by its code', async () => {
      // A second class, so the filter has something to leave out.
      const dollar = {
        ...products[0],
        id: 'b0000000-0000-4000-8000-000000000001',
        code: 'DOL',
        name: 'Futuro de Dólar Comercial',
        asset_class: { id: 2, code: 'FX_FUTURE', name: 'Futuros de Moeda' },
        instrument_count: 1,
      };
      server.use(
        http.get(url('/products'), () => HttpResponse.json({ items: [...products, dollar] })),
        http.get(url('/instruments'), () =>
          HttpResponse.json({
            items: [
              ...instruments.map((i) => ({ ...i, last_reference: null })),
              {
                id: 'b0000000-0000-4000-8000-0000000000d1',
                code: 'DOLX26',
                product_id: dollar.id,
                product_code: 'DOL',
                maturity_date: '2026-12-01',
                created_at: '2026-10-01T09:00:00-03:00',
                last_reference: null,
              },
            ],
          }),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');
      const contract = modal.getByRole('combobox', { name: 'Contrato' });
      await waitFor(() => {
        expect(contract).toBeEnabled();
      });
      const option = (code: string) => screen.queryByRole('option', { name: code, hidden: true });

      await user.click(contract);
      expect(option('DOLX26')).toBeInTheDocument();
      expect(option('DI1F28')).toBeInTheDocument();
      await user.click(screen.getByRole('option', { name: 'DOLX26', hidden: true }));
      expect(contract).toHaveValue('DOLX26');

      await user.click(modal.getByRole('combobox', { name: 'Classe de ativo' }));
      await user.click(
        await screen.findByRole('option', { name: 'Futuros de Taxa de Juros', hidden: true }),
      );
      // DOLX26 is not of that class: it is cleared and no longer offered.
      expect(contract).toHaveValue('');
      await user.click(contract);
      expect(option('DOLX26')).not.toBeInTheDocument();
      expect(option('DI1F28')).toBeInTheDocument();

      await user.type(contract, 'F29');
      expect(option('DI1F29')).toBeInTheDocument();
      expect(option('DI1F28')).not.toBeInTheDocument();
    });

    it('§11.3 a class change keeps a contract of the chosen class', async () => {
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');
      await chooseContract(user, modal, 'DI1F28');

      await user.click(modal.getByRole('combobox', { name: 'Classe de ativo' }));
      await user.click(
        await screen.findByRole('option', { name: 'Futuros de Taxa de Juros', hidden: true }),
      );

      expect(modal.getByRole('combobox', { name: 'Contrato' })).toHaveValue('DI1F28');
    });
  });

  describe('Processar (OQ-21, user 2026-10-18)', () => {
    async function openProcessar(user: ReturnType<typeof renderApp>['user']) {
      await user.click(screen.getByRole('button', { name: 'Processar' }));
      return within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
    }

    it('§10.1 prefills the whole period with Tudo (P19 dropped)', async () => {
      const { user } = await openLedger();

      const modal = await openProcessar(user);

      expect(modal.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('14/10/2026');
      expect(modal.getByRole('textbox', { name: 'Data final' })).toHaveValue('16/10/2026');
      expect(modal.getByRole('radio', { name: 'Tudo' })).toBeChecked();
    });

    it('§11.3 "Processar caixa" starts at Caixa D0 when only D0 is behind', async () => {
      failCash('2026-10-16');
      const { user } = await openLedger();

      await user.click(await screen.findByRole('button', { name: 'Processar caixa' }));

      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
      expect(modal.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('16/10/2026');
      expect(modal.getByRole('textbox', { name: 'Data final' })).toHaveValue('16/10/2026');
      expect(modal.getByRole('radio', { name: 'Caixa' })).toBeChecked();
    });

    it('§11.3 "Processar caixa" is offered when Caixa D0 was never processed', async () => {
      const { user } = await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-17');

      await user.click(await screen.findByRole('button', { name: 'Processar caixa' }));

      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
      expect(modal.getByRole('textbox', { name: 'Data inicial' })).toHaveValue('17/10/2026');
      expect(modal.getByRole('textbox', { name: 'Data final' })).toHaveValue('17/10/2026');
    });

    it('§10.1 previews and queues the job without leaving Lançamentos', async () => {
      server.use(
        http.get(url('/processing/preview'), () =>
          HttpResponse.json({ ...preview, end_date: '2026-10-15', total_days: 2, scope: 'CASH' }),
        ),
      );
      const bodies = captureBodies('/processing/requests');
      const { user, router } = await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-15');
      const modal = await openProcessar(user);
      await user.click(modal.getByRole('radio', { name: 'Caixa' }));

      expect(
        await modal.findByRole('group', { name: 'Estado anterior do caixa' }),
      ).toHaveTextContent('Estado inicial (sem lançamentos anteriores)');
      expect(modal.queryByRole('group', { name: 'Estado anterior das posições' })).toBeNull();
      await user.click(modal.getByRole('button', { name: 'Confirmar processamento' }));

      expect(
        await screen.findByText(
          'Processamento colocado na fila. Acompanhe em Central de Controle.',
        ),
      ).toBeInTheDocument();
      expect(bodies).toEqual([{ start_date: '2026-10-14', end_date: '2026-10-15', scope: 'CASH' }]);
      expect(router.state.location.pathname).toBe('/lancamentos');
    });
  });

  describe('Processar: API errors (OQ-15)', () => {
    it('OQ-15 shows an error on scope under the Escopo group', async () => {
      server.use(
        http.post(url('/processing/requests'), () =>
          problem(422, [fieldError('VALIDATION_ERROR', 'Escopo não aceito.', 'scope')]),
        ),
      );
      const { user } = await openLedger();
      await user.click(screen.getByRole('button', { name: 'Processar' }));
      const modal = within(await screen.findByRole('dialog', { name: 'Solicitar processamento' }));
      await modal.findByRole('group', { name: 'Estado anterior do caixa' });

      await user.click(modal.getByRole('button', { name: 'Confirmar processamento' }));

      const scope = await modal.findByRole('radiogroup', { name: 'Escopo' });
      await waitFor(() => {
        expect(scope).toHaveAccessibleDescription('Escopo não aceito.');
      });
    });
  });

  describe('Novo lançamento modal: state (§11.3)', () => {
    it('§11.3 each opening starts again at Operação → Compra with blank fields', async () => {
      const { user } = await openLedger();
      let modal = await openNew(user, 'Retirada');
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '1.000,00');
      await user.click(modal.getByRole('button', { name: 'Fechar' }));
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });

      await user.click(screen.getByRole('button', { name: 'Novo lançamento' }));
      modal = within(await screen.findByRole('dialog', { name: 'Novo lançamento' }));

      expect(modal.getByRole('radio', { name: 'Operação' })).toBeChecked();
      expect(modal.getByRole('radio', { name: 'Compra' })).toBeChecked();
      await user.click(modal.getByRole('radio', { name: 'Caixa' }));
      expect(modal.getByRole('radio', { name: 'Aporte' })).toBeChecked();
      expect(modal.getByRole('textbox', { name: 'Valor (R$)' })).toHaveValue('');
    });

    it('OQ-15 locks the kind of entry while a save runs', async () => {
      let release: () => void = () => undefined;
      server.use(
        http.post(url('/ledger/entries'), async () => {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return undefined;
        }),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Aporte');
      await user.type(modal.getByRole('textbox', { name: 'Valor (R$)' }), '1.000,00');
      await user.click(modal.getByRole('button', { name: 'Registrar aporte' }));

      await waitFor(() => {
        expect(modal.getByRole('radio', { name: 'Operação' })).toBeDisabled();
      });
      expect(modal.getByRole('radio', { name: 'Retirada' })).toBeDisabled();
      release();
    });

    it('§12 says so on Classe de ativo when the classes fail to load; contracts still work', async () => {
      server.use(
        http.get(url('/products'), () =>
          problem(500, [fieldError('VALIDATION_ERROR', 'Erro interno.')]),
        ),
      );
      const { user } = await openLedger();
      const modal = await openNew(user, 'Compra');

      expect(
        await modal.findByText('Não foi possível carregar as classes de ativo.'),
      ).toBeInTheDocument();
      expect(modal.queryByText('Não foi possível carregar os contratos.')).not.toBeInTheDocument();
      await chooseContract(user, modal, 'DI1F28');
    });
  });

  describe('delete (§6.1)', () => {
    const sale = 'Venda DI1F28 -4 16/10/2026 15:00 PU 89.102,22';
    // Accessible names keep the no-break space Intl puts after "R$".
    const withdrawal = 'Retirada 16/10/2026 17:30 -R$\u00a050.000,00';

    it('§6.1 deletes one trade after confirmation, by its id; there is no edit action', async () => {
      answerDeletes(serveEntries());
      const bodies = captureBodies('/ledger/entries/deletions');
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      expect(screen.queryByRole('menuitem', { name: /Editar/ })).not.toBeInTheDocument();
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamento' }));
      expect(dialog.getByText(sale, { exact: false })).toBeInTheDocument();
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await screen.findByText('Lançamento excluído.')).toBeInTheDocument();
      expect(bodies).toEqual([{ ids: [tradeEntries[2]?.id] }]);
      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      expect(
        screen.queryByRole('checkbox', { name: `Selecionar ${sale}` }),
      ).not.toBeInTheDocument();
    });

    it('§6.1 deletes one cash entry after confirmation', async () => {
      answerDeletes(serveEntries());
      const { user } = await openLedger();

      await user.click(
        rowNamed(withdrawal).getByRole('button', { name: `Ações de ${withdrawal}` }),
      );
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamento' }));
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      expect(
        screen.queryByRole('checkbox', { name: `Selecionar ${withdrawal}` }),
      ).not.toBeInTheDocument();
    });

    it('§6.1 a failed single delete keeps the entry and shows why', async () => {
      server.use(
        http.post(url('/ledger/entries/deletions'), () =>
          problem(404, [fieldError('NOT_FOUND', 'Lançamento não encontrado.')]),
        ),
      );
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamento' }));
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await dialog.findByText('Lançamento não encontrado.')).toBeInTheDocument();
      expect(screen.getByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§6.1 a new range or search drops the selection', async () => {
      serveSearch({ DI1F28: DI1F28_ENTRIES });
      const { user, router } = await openLedger();
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      expect(screen.getByRole('button', { name: 'Excluir selecionados' })).toBeInTheDocument();

      await router.navigate('/lancamentos?inicio=2026-10-14&fim=2026-10-15');
      expect(await screen.findByText('3 lançamentos encontrados')).toBeInTheDocument();
      await router.navigate(FULL_RANGE);
      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();

      expect(screen.getByRole('checkbox', { name: `Selecionar ${sale}` })).not.toBeChecked();
      expect(
        screen.queryByRole('button', { name: 'Excluir selecionados' }),
      ).not.toBeInTheDocument();

      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      const box = screen.getByRole('textbox', { name: 'Buscar' });
      await user.type(box, 'DI1F28');
      expect(await screen.findByText('2 lançamentos encontrados')).toBeInTheDocument();
      await user.clear(box);
      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();

      expect(screen.getByRole('checkbox', { name: `Selecionar ${sale}` })).not.toBeChecked();
    });

    it('§6.1 tells apart two same-day cash entries of the same amount by their time', async () => {
      const withdrawalEntry = cashEntries[1];
      const twin = { ...withdrawalEntry, id: 'twin', time: '18:05:00' };
      server.use(
        http.get(url('/ledger/entries'), () =>
          HttpResponse.json({ items: [twin, withdrawalEntry], next_cursor: null }),
        ),
      );
      await openLedger();

      expect(
        screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('checkbox', {
          name: 'Selecionar Retirada 16/10/2026 18:05 -R$\u00a050.000,00',
        }),
      ).toBeInTheDocument();
    });

    it('§6.1 "Voltar" leaves the entry in place', async () => {
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      await user.click(await screen.findByRole('button', { name: 'Voltar' }));

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
      expect(screen.getByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§6.1 deletes the selected entries, of both types, in one atomic request', async () => {
      answerDeletes(serveEntries());
      const bodies = captureBodies('/ledger/entries/deletions');
      const { user } = await openLedger();

      expect(
        screen.queryByRole('button', { name: 'Excluir selecionados' }),
      ).not.toBeInTheDocument();
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }));
      await user.click(screen.getByRole('button', { name: 'Excluir selecionados' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamentos' }));
      expect(dialog.getByText(/2 lançamentos selecionados/)).toBeInTheDocument();
      expect(dialog.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        withdrawal,
        sale,
      ]);
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await screen.findByText('2 lançamentos excluídos.')).toBeInTheDocument();
      expect(bodies).toEqual([{ ids: [cashEntries[1]?.id, tradeEntries[2]?.id] }]);
      expect(await screen.findByText('3 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§6.1 "Selecionar todos" selects every listed entry', async () => {
      const { user } = await openLedger();

      await user.click(screen.getByRole('checkbox', { name: 'Selecionar todos' }));
      await user.click(screen.getByRole('button', { name: 'Excluir selecionados' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamentos' }));
      expect(dialog.getByText(/5 lançamentos selecionados/)).toBeInTheDocument();
    });

    it('§6.1 a failed multiple delete removes nothing and shows the error', async () => {
      server.use(
        http.post(url('/ledger/entries/deletions'), () =>
          problem(404, [fieldError('NOT_FOUND', 'Lançamento não encontrado.')]),
        ),
      );
      const { user } = await openLedger();

      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }));
      await user.click(screen.getByRole('button', { name: 'Excluir selecionados' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamentos' }));
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await dialog.findByText('Lançamento não encontrado.')).toBeInTheDocument();
      expect(screen.getByText('5 lançamentos encontrados')).toBeInTheDocument();
    });

    /**
     * Another tab or user deleted the sale after this screen listed it (QA 2026-10-19 #1): the
     * API answers the first deletion 404, deleting nothing (OQ-32), and lists the entries
     * without the sale from then on; a later deletion succeeds.
     */
    function saleDeletedElsewhere() {
      const ledger = serveEntries();
      let deletions = 0;
      server.use(
        http.post(url('/ledger/entries/deletions'), async ({ request }) => {
          deletions += 1;
          if (deletions === 1) {
            ledger.items = ledger.items.filter((e) => e.id !== tradeEntries[2]?.id);
            return problem(404, [fieldError('NOT_FOUND', 'Lançamento não encontrado.')]);
          }
          const { ids } = (await request.clone().json()) as { ids: string[] };
          ledger.items = ledger.items.filter((e) => !ids.includes(e.id));
          return new HttpResponse(null, { status: 204 });
        }),
      );
    }

    it('OQ-32 a 404 on a multiple delete refreshes the list and a retry deletes what is left', async () => {
      saleDeletedElsewhere();
      const bodies = captureBodies('/ledger/entries/deletions');
      const { user } = await openLedger();

      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${sale}` }));
      await user.click(screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }));
      await user.click(screen.getByRole('button', { name: 'Excluir selecionados' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamentos' }));
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      // Nothing was deleted (all or nothing); the list now omits the vanished entry, and so do
      // the selection and the dialog.
      expect(await dialog.findByText('Lançamento não encontrado.')).toBeInTheDocument();
      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      await waitFor(() => {
        expect(dialog.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
          withdrawal,
        ]);
      });
      expect(dialog.getByText(/1 lançamento selecionado/)).toBeInTheDocument();
      // The user is told which entry left the dialog, since the 404 does not name it.
      expect(
        screen.getByText(`Retirado da exclusão por já não existir: ${sale}.`),
      ).toBeInTheDocument();

      await user.click(dialog.getByRole('button', { name: 'Excluir' }));
      expect(await screen.findByText('Lançamento excluído.')).toBeInTheDocument();
      expect(bodies).toEqual([
        { ids: [cashEntries[1]?.id, tradeEntries[2]?.id] },
        { ids: [cashEntries[1]?.id] },
      ]);
      expect(await screen.findByText('3 lançamentos encontrados')).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Excluir selecionados' }),
      ).not.toBeInTheDocument();
    });

    it('OQ-32 a 404 for an entry already deleted elsewhere closes the dialog and refreshes the list', async () => {
      saleDeletedElsewhere();
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = await screen.findByRole('dialog', { name: 'Excluir lançamento' });
      await user.click(within(dialog).getByRole('button', { name: 'Excluir' }));

      expect(
        await screen.findByText(
          'Lançamento não encontrado. Ele já havia sido excluído; a lista foi atualizada.',
        ),
      ).toBeInTheDocument();
      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      await waitFor(() => {
        expect(screen.queryByRole('dialog', { name: 'Excluir lançamento' })).toBeNull();
      });
      expect(
        screen.queryByRole('checkbox', { name: `Selecionar ${sale}` }),
      ).not.toBeInTheDocument();
    });
  });
});
