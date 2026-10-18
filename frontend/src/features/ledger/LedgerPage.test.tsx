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

import { cashMovements, IDS, trades } from '@/api/mocks/fixtures';
import { fieldError, problem, url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { addDays, formatDate, todayInSaoPaulo } from '@/shared/format';
import { renderApp } from '@/test/render';

// Expected figures are the fixture scenario's values (src/api/mocks/fixtures.ts), formatted
// in pt-BR. Intl puts a no-break space after "R$"; Testing Library's default normalizer turns
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

/** Records the JSON body of every request to `path`, then lets the mock answer it. */
function captureBodies(method: 'post', path: string) {
  const bodies: unknown[] = [];
  server.use(
    http[method](url(path), async ({ request }) => {
      bodies.push(await request.clone().json());
      return undefined;
    }),
  );
  return bodies;
}

async function openNew(user: ReturnType<typeof renderApp>['user'], item: string) {
  await user.click(screen.getByRole('button', { name: 'Novo lançamento' }));
  await user.click(await screen.findByRole('menuitem', { name: item }));
  return within(await screen.findByRole('dialog'));
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
  drawer: BoundFunctions<typeof queries>,
  code: string,
) {
  const select = drawer.getByRole('combobox', { name: 'Contrato' });
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

    it('§11.3 merges trades and cash movements, newest first, in pt-BR formats', async () => {
      await openLedger();
      await screen.findAllByText('Futuros');

      expect(bodyRows().map(cellTexts)).toEqual([
        [
          '',
          '16/10/2026 15:00',
          'Futuros',
          'Venda',
          'DI1F28',
          '-4',
          '89.102,22',
          '9,95%',
          '+R$ 356.408,89',
          '',
        ],
        ['', '16/10/2026', 'Caixa', 'Retirada', '—', '—', '—', '—', '-R$ 50.000,00', ''],
        [
          '',
          '15/10/2026 10:30',
          'Futuros',
          'Compra',
          'DI1F29',
          '+5',
          '82.057,00',
          '9,32%',
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
          '10,00%',
          '-R$ 890.064,63',
          '',
        ],
        ['', '14/10/2026', 'Caixa', 'Aporte', '—', '—', '—', '—', '+R$ 1.500.000,00', ''],
      ]);
    });

    it('§11.3 sorts by Data e hora, descending by default, ascending on click', async () => {
      const { user } = await openLedger();
      const header = screen.getByRole('columnheader', { name: 'Data e hora' });
      expect(header).toHaveAttribute('aria-sort', 'descending');

      await user.click(within(header).getByRole('button'));

      expect(header).toHaveAttribute('aria-sort', 'ascending');
      expect(cellTexts(bodyRows()[0] as HTMLElement)[1]).toBe('14/10/2026');
      expect(cellTexts(bodyRows()[4] as HTMLElement)[1]).toBe('16/10/2026 15:00');
    });

    it('§11.3 the range is inclusive on both ends', async () => {
      await openLedger('/lancamentos?inicio=2026-10-15&fim=2026-10-16');

      expect(screen.getByText('3 lançamentos encontrados')).toBeInTheDocument();
      expect(bodyRows().map((row) => cellTexts(row)[1])).toEqual([
        '16/10/2026 15:00',
        '16/10/2026',
        '15/10/2026 10:30',
      ]);
    });

    it('§11.3 a one-day range keeps the entries of that day', async () => {
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-14');

      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();
    });

    it('§11.3 searches by asset from the URL (busca)', async () => {
      await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-16&busca=DI1F28');

      expect(screen.getByRole('textbox', { name: 'Buscar' })).toHaveValue('DI1F28');
      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();
      expect(bodyRows().map((row) => cellTexts(row)[4])).toEqual(['DI1F28', 'DI1F28']);
    });

    it('§11.3 typing a search filters the list and keeps it in the URL', async () => {
      const { user, router } = await openLedger();

      await user.type(screen.getByRole('textbox', { name: 'Buscar' }), 'retirada');

      expect(await screen.findByText('1 lançamento encontrado')).toBeInTheDocument();
      expect(router.state.location.search).toContain('busca=retirada');
      expect(cellTexts(bodyRows()[0] as HTMLElement)[3]).toBe('Retirada');
    });

    it('§11.3 without inicio/fim, lists the 30 days ending today (São Paulo)', async () => {
      const today = todayInSaoPaulo();
      const start = addDays(today, -29);
      const seen: string[] = [];
      server.use(
        http.get(url('/trades'), ({ request }) => {
          seen.push(new URL(request.url).search);
          return HttpResponse.json({ items: [] });
        }),
        http.get(url('/cash-movements'), () => HttpResponse.json({ items: [] })),
      );

      await openLedger('/lancamentos?busca=DI1F29');

      expect(seen[0]).toBe(`?start_date=${start}&end_date=${today}&search=DI1F29`);
      expect(screen.getByRole('button', { name: 'Período' })).toHaveTextContent(
        `${formatDate(start)} – ${formatDate(today)}`,
      );
    });

    it('§11.3 shows the empty state for a range without entries', async () => {
      await openLedger('/lancamentos?inicio=2026-10-01&fim=2026-10-05');

      expect(screen.getByText('0 lançamentos encontrados')).toBeInTheDocument();
      expect(screen.getByText('Nenhum lançamento no período.')).toBeInTheDocument();
    });

    it('§12 shows the API error with a retry', async () => {
      server.use(
        http.get(url('/trades'), () =>
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
      expect(cellTexts(bodyRows()[0] as HTMLElement)[2]).toBe('—');
    });

    it('§11.3 clearing busca in the URL clears the search box and keeps it cleared', async () => {
      const { router } = await openLedger(`${FULL_RANGE}&busca=DI1F28`);
      expect(screen.getByText('2 lançamentos encontrados')).toBeInTheDocument();

      await router.navigate(FULL_RANGE);

      expect(await screen.findByText('5 lançamentos encontrados')).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: 'Buscar' })).toHaveValue('');
      await new Promise((resolve) => setTimeout(resolve, 400));
      expect(router.state.location.search).not.toContain('busca');
    });
  });

  describe('cash strip (OQ-19 item 3)', () => {
    it('§11.3 shows Caixa D−1 and Caixa D0 for the range end, with the stale marker', async () => {
      await openLedger();

      const before = within(screen.getByRole('group', { name: 'Caixa D−1' }));
      const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
      expect(before.getByText('15/10/2026')).toBeInTheDocument();
      expect(await before.findByText('R$ 199.650,37')).toBeInTheDocument();
      expect(before.queryByText('Desatualizado')).not.toBeInTheDocument();
      expect(end.getByText('16/10/2026')).toBeInTheDocument();
      expect(await end.findByText('R$ 506.059,27')).toBeInTheDocument();
      expect(end.getByText('Desatualizado')).toBeInTheDocument();
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

  it('§10.4 a write refreshes the strip: Caixa D0 turns stale', async () => {
    const { user } = await openLedger('/lancamentos?inicio=2026-10-14&fim=2026-10-15');
    const end = within(screen.getByRole('group', { name: 'Caixa D0' }));
    expect(await end.findByText('R$ 199.650,37')).toBeInTheDocument();
    expect(end.queryByText('Desatualizado')).not.toBeInTheDocument();

    const drawer = await openNew(user, 'Aporte');
    await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '15/10/2026');
    await user.type(drawer.getByRole('textbox', { name: 'Valor (R$)' }), '100,00');
    await user.click(drawer.getByRole('button', { name: 'Registrar aporte' }));

    expect(await end.findByText('Desatualizado')).toBeInTheDocument();
  });

  describe('Compra / Venda drawer (§6.1)', () => {
    it('§6.1 registers a compra typed as PU, positive quantity', async () => {
      const bodies = captureBodies('post', '/trades');
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');

      await chooseContract(user, drawer, 'DI1F29');
      await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      fireEvent.change(drawer.getByLabelText('Hora', { exact: false }), {
        target: { value: '16:45' },
      });
      await user.type(drawer.getByRole('textbox', { name: 'Quantidade' }), '3');
      await user.type(drawer.getByRole('textbox', { name: 'PU' }), '80.000,00');
      await user.click(drawer.getByRole('button', { name: 'Registrar compra' }));

      expect(await screen.findByText('Compra registrada.')).toBeInTheDocument();
      expect(bodies).toEqual([
        {
          asset_id: IDS.di1f29,
          trade_date: '2026-10-16',
          trade_time: '16:45:00',
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
      const bodies = captureBodies('post', '/trades');
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Venda');

      await chooseContract(user, drawer, 'DI1F28');
      await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      fireEvent.change(drawer.getByLabelText('Hora', { exact: false }), {
        target: { value: '17:05' },
      });
      await user.type(drawer.getByRole('textbox', { name: 'Quantidade' }), '2');
      await user.click(drawer.getByRole('radio', { name: 'Taxa a.a. (%)' }));
      await user.type(drawer.getByRole('textbox', { name: 'Taxa a.a. (%)' }), '10,45');
      await user.click(drawer.getByRole('button', { name: 'Registrar venda' }));

      expect(await screen.findByText('Venda registrada.')).toBeInTheDocument();
      expect(bodies).toEqual([
        {
          asset_id: IDS.di1f28,
          trade_date: '2026-10-16',
          trade_time: '17:05:00',
          signed_quantity: -2,
          input_kind: 'RATE',
          execution_rate: '0.1045',
        },
      ]);
    });

    it('OQ-13 suggests today and the current time, and has no PU/rate preview', async () => {
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');

      expect(drawer.getByRole('textbox', { name: 'Data' })).toHaveValue(
        formatDate(todayInSaoPaulo()),
      );
      expect(drawer.getByLabelText<HTMLInputElement>('Hora', { exact: false }).value).toMatch(
        /^\d{2}:\d{2}$/,
      );
      await user.type(drawer.getByRole('textbox', { name: 'PU' }), '89.006,46');
      expect(drawer.queryByRole('textbox', { name: 'Taxa a.a. (%)' })).not.toBeInTheDocument();
      expect(drawer.queryByText(/%$/)).not.toBeInTheDocument();
    });

    it('OQ-15 keeps the drawer open while saving, so the result is never lost', async () => {
      let release: () => void = () => undefined;
      server.use(
        http.post(url('/trades'), async () => {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return undefined;
        }),
      );
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');
      await chooseContract(user, drawer, 'DI1F29');
      await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(drawer.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(drawer.getByRole('textbox', { name: 'PU' }), '80.000,00');
      await user.click(drawer.getByRole('button', { name: 'Registrar compra' }));

      await user.keyboard('{Escape}');
      // Past the drawer's close transition: a closing drawer would be gone by now.
      await new Promise((resolve) => setTimeout(resolve, 400));
      expect(drawer.queryByRole('button', { name: 'Fechar' })).not.toBeInTheDocument();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(drawer.getByRole('button', { name: 'Registrar compra' })).toBeInTheDocument();
      release();
      expect(await screen.findByText('Compra registrada.')).toBeInTheDocument();
    });

    it('§6.1 checks the required fields before sending', async () => {
      const bodies = captureBodies('post', '/trades');
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');

      await user.click(drawer.getByRole('button', { name: 'Registrar compra' }));

      expect(drawer.getByText('Selecione um contrato.')).toBeInTheDocument();
      expect(
        drawer.getByText('Informe uma quantidade inteira maior que zero.'),
      ).toBeInTheDocument();
      expect(drawer.getByText('Informe o PU.')).toBeInTheDocument();
      expect(bodies).toEqual([]);
    });

    it('OQ-3 shows the decimal-place error of a PU on its field', async () => {
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');

      await chooseContract(user, drawer, 'DI1F29');
      await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(drawer.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(drawer.getByRole('textbox', { name: 'PU' }), '80.000,12345678901');
      await user.click(drawer.getByRole('button', { name: 'Registrar compra' }));

      expect(await drawer.findByText('Use no máximo 10 casas decimais.')).toBeInTheDocument();
      expect(drawer.getByRole('textbox', { name: 'PU' })).toHaveAttribute('aria-invalid', 'true');
    });

    it('OQ-3 shows the decimal-place error of a rate on its field', async () => {
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');

      await chooseContract(user, drawer, 'DI1F29');
      await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '16/10/2026');
      await user.type(drawer.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.click(drawer.getByRole('radio', { name: 'Taxa a.a. (%)' }));
      // 10,12345678901% = 0.1012345678901: 13 places, one more than OQ-3 allows.
      await user.type(drawer.getByRole('textbox', { name: 'Taxa a.a. (%)' }), '10,12345678901');
      await user.click(drawer.getByRole('button', { name: 'Registrar compra' }));

      expect(await drawer.findByText('Use no máximo 12 casas decimais.')).toBeInTheDocument();
      expect(drawer.getByRole('textbox', { name: 'Taxa a.a. (%)' })).toHaveAttribute(
        'aria-invalid',
        'true',
      );
    });

    it.each([
      ['FUTURE_DATE', 'A data não pode ser posterior a hoje.'],
      ['CONTRACT_MATURED', 'O contrato já venceu nesta data.'],
    ] as const)('OQ-14 / OQ-1 shows %s on the Data field', async (code, message) => {
      server.use(
        http.post(url('/trades'), () => problem(422, [fieldError(code, message, 'trade_date')])),
      );
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');

      await chooseContract(user, drawer, 'DI1F27');
      await user.type(drawer.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(drawer.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(drawer.getByRole('button', { name: 'Registrar compra' }));

      expect(await drawer.findByText(message)).toBeInTheDocument();
      expect(drawer.getByRole('textbox', { name: 'Data' })).toHaveAttribute('aria-invalid', 'true');
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('OQ-15 shows every message when two API fields belong to the same input', async () => {
      server.use(
        http.post(url('/trades'), () =>
          problem(422, [
            fieldError('VALIDATION_ERROR', 'Informe um número válido.', 'execution_rate'),
            fieldError('VALIDATION_ERROR', 'Informe o PU ou a taxa.', 'input_kind'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');

      await chooseContract(user, drawer, 'DI1F27');
      await user.type(drawer.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(drawer.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(drawer.getByRole('button', { name: 'Registrar compra' }));

      expect(await drawer.findByText(/Informe um número válido\./)).toBeInTheDocument();
      expect(drawer.getByText(/Informe o PU ou a taxa\./)).toBeInTheDocument();
    });

    it('OQ-15 shows an error without a field above the form', async () => {
      server.use(
        http.post(url('/trades'), () =>
          problem(409, [fieldError('VALIDATION_ERROR', 'Lançamentos bloqueados no momento.')]),
        ),
      );
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Compra');

      await chooseContract(user, drawer, 'DI1F27');
      await user.type(drawer.getByRole('textbox', { name: 'Quantidade' }), '1');
      await user.type(drawer.getByRole('textbox', { name: 'PU' }), '99.000,00');
      await user.click(drawer.getByRole('button', { name: 'Registrar compra' }));

      expect(await drawer.findByRole('alert')).toHaveTextContent(
        'Lançamentos bloqueados no momento.',
      );
    });
  });

  describe('Aporte / Retirada drawer (§6.2)', () => {
    it('§6.2 registers an aporte with a positive amount', async () => {
      const bodies = captureBodies('post', '/cash-movements');
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Aporte');

      await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      await user.type(drawer.getByRole('textbox', { name: 'Valor (R$)' }), '2.500,50');
      await user.click(drawer.getByRole('button', { name: 'Registrar aporte' }));

      expect(await screen.findByText('Aporte registrado.')).toBeInTheDocument();
      expect(bodies).toEqual([
        { movement_date: '2026-10-15', movement_type: 'DEPOSIT', amount: '2500.50' },
      ]);
      expect(await screen.findByText('+R$ 2.500,50')).toBeInTheDocument();
    });

    it('§6.2 registers a retirada; the amount is sent positive', async () => {
      const bodies = captureBodies('post', '/cash-movements');
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Retirada');

      await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      await user.type(drawer.getByRole('textbox', { name: 'Valor (R$)' }), '1.000');
      await user.click(drawer.getByRole('button', { name: 'Registrar retirada' }));

      expect(await screen.findByText('Retirada registrada.')).toBeInTheDocument();
      expect(bodies).toEqual([
        { movement_date: '2026-10-15', movement_type: 'WITHDRAWAL', amount: '1000' },
      ]);
      expect(await screen.findByText('-R$ 1.000,00')).toBeInTheDocument();
    });

    it('OQ-3 shows the decimal-place error of an amount on its field', async () => {
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Aporte');

      await typeDate(user, drawer.getByRole('textbox', { name: 'Data' }), '15/10/2026');
      await user.type(drawer.getByRole('textbox', { name: 'Valor (R$)' }), '10,505');
      await user.click(drawer.getByRole('button', { name: 'Registrar aporte' }));

      expect(await drawer.findByText('Use no máximo 2 casas decimais.')).toBeInTheDocument();
      expect(drawer.getByRole('textbox', { name: 'Valor (R$)' })).toHaveAttribute(
        'aria-invalid',
        'true',
      );
    });

    it('OQ-14 shows FUTURE_DATE on the Data field', async () => {
      server.use(
        http.post(url('/cash-movements'), () =>
          problem(422, [
            fieldError('FUTURE_DATE', 'A data não pode ser posterior a hoje.', 'movement_date'),
          ]),
        ),
      );
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Aporte');

      await user.type(drawer.getByRole('textbox', { name: 'Valor (R$)' }), '100,00');
      await user.click(drawer.getByRole('button', { name: 'Registrar aporte' }));

      expect(await drawer.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
      expect(drawer.getByRole('textbox', { name: 'Data' })).toHaveAttribute('aria-invalid', 'true');
    });

    it('§6.2 rejects a value that is not a pt-BR number before sending', async () => {
      const bodies = captureBodies('post', '/cash-movements');
      const { user } = await openLedger();
      const drawer = await openNew(user, 'Aporte');

      await user.type(drawer.getByRole('textbox', { name: 'Valor (R$)' }), '1,000.50');
      await user.click(drawer.getByRole('button', { name: 'Registrar aporte' }));

      expect(drawer.getByText('Informe um valor válido, como 1.234,56.')).toBeInTheDocument();
      expect(bodies).toEqual([]);
    });
  });

  describe('delete (§6.1)', () => {
    const sale = 'Venda DI1F28 -4 16/10/2026 15:00 PU 89.102,22';
    // Accessible names keep the no-break space Intl puts after "R$".
    const withdrawal = 'Retirada 16/10/2026 -R$\u00a050.000,00 registrada às 17:30';

    it('§6.1 deletes one trade after confirmation; there is no edit action', async () => {
      const { user } = await openLedger();

      await user.click(rowNamed(sale).getByRole('button', { name: `Ações de ${sale}` }));
      expect(screen.queryByRole('menuitem', { name: /Editar/ })).not.toBeInTheDocument();
      await user.click(await screen.findByRole('menuitem', { name: 'Excluir' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Excluir lançamento' }));
      expect(dialog.getByText(sale, { exact: false })).toBeInTheDocument();
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await screen.findByText('Lançamento excluído.')).toBeInTheDocument();
      expect(await screen.findByText('4 lançamentos encontrados')).toBeInTheDocument();
      expect(
        screen.queryByRole('checkbox', { name: `Selecionar ${sale}` }),
      ).not.toBeInTheDocument();
    });

    it('§6.1 deletes one cash movement after confirmation', async () => {
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
        http.delete(url('/trades/:id'), () =>
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

    it('§6.1 tells apart two same-day cash movements of the same amount', async () => {
      const twin = { ...cashMovements[1], id: 'twin', created_at: '2026-10-16T18:05:00-03:00' };
      server.use(
        http.get(url('/cash-movements'), () =>
          HttpResponse.json({ items: [twin, cashMovements[1]] }),
        ),
      );
      await openLedger();

      expect(
        screen.getByRole('checkbox', { name: `Selecionar ${withdrawal}` }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole('checkbox', {
          name: 'Selecionar Retirada 16/10/2026 -R$\u00a050.000,00 registrada às 18:05',
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

    it('§6.1 deletes the selected entries in one atomic request', async () => {
      const bodies = captureBodies('post', '/ledger/deletions');
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
        sale,
        withdrawal,
      ]);
      await user.click(dialog.getByRole('button', { name: 'Excluir' }));

      expect(await screen.findByText('2 lançamentos excluídos.')).toBeInTheDocument();
      expect(bodies).toEqual([
        { trade_ids: [trades[2]?.id], cash_movement_ids: [cashMovements[1]?.id] },
      ]);
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
        http.post(url('/ledger/deletions'), () =>
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
  });
});
