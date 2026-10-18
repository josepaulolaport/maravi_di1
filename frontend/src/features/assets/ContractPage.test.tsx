import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { IDS } from '@/api/mocks/fixtures';
import { problem, url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { renderApp } from '@/test/render';

// Expected values come from the fixture scenario (src/api/mocks/fixtures.ts), with today fixed
// at MOCK_TODAY (18/10/2026, São Paulo). DI1F28 matures on 03/01/2028, so its calendar is
// 19/09–18/10. Its current observations in that window: 24/09 B3, 30/09 MANUAL, 05/10 MANUAL,
// 08/10 B3, 09/10 MANUAL, 14/10 MANUAL, 15/10 B3, 16/10 MANUAL revision 2 (89250.3147019396,
// 0.0980) and B3 (89240.4279488087, 0.0981). Nothing on 17/10 or 18/10.

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-18T12:00:00-03:00'));
});
afterEach(() => {
  vi.useRealTimers();
});

const F28 = `/ativos/contratos/${IDS.di1f28}`;

async function openContract(route = F28) {
  const result = renderApp(route);
  await screen.findByRole('heading', { name: 'DI1F28' });
  await screen.findByRole('table', { name: 'Calendário de preços de referência' });
  return result;
}

function dayRow(date: string) {
  const cell = screen.getByText(date, { selector: 'td' });
  const row = cell.closest('tr');
  if (!row) throw new Error(`no row for ${date}`);
  return within(row);
}

function cells(date: string) {
  return dayRow(date)
    .getAllByRole('cell')
    .slice(0, 4)
    .map((cell) => cell.textContent);
}

async function rowAction(user: ReturnType<typeof renderApp>['user'], date: string, item: string) {
  await user.click(dayRow(date).getByRole('button', { name: `Ações de ${date}` }));
  await user.click(await screen.findByRole('menuitem', { name: item }));
}

describe('Ativos: contrato (§11.2)', () => {
  it('§11.2 shows the breadcrumb, the maturity badge and the product name', async () => {
    await openContract();

    const breadcrumb = within(screen.getByRole('navigation', { name: 'Trilha' }));
    expect(breadcrumb.getByRole('link', { name: 'Ativos' })).toHaveAttribute('href', '/ativos');
    expect(breadcrumb.getByRole('link', { name: 'DI1' })).toHaveAttribute(
      'href',
      `/ativos/produtos/${IDS.di1}`,
    );
    expect(breadcrumb.getByText('DI1F28')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('Vencimento: 03/01/2028')).toBeInTheDocument();
    expect(
      await screen.findByText('Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia'),
    ).toBeInTheDocument();
  });

  it('§11.2 has no rate ↔ PU calculator (OQ-19)', async () => {
    await openContract();

    expect(screen.queryByText(/calculadora/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /taxa|pu/i })).not.toBeInTheDocument();
  });

  it('§5 lists every calendar day of the last 30 days, newest first, with its count', async () => {
    await openContract();

    const table = within(screen.getByRole('table', { name: 'Calendário de preços de referência' }));
    const headers = table.getAllByRole('columnheader').map((th) => th.textContent);
    expect(headers).toEqual(['Data', 'PU', 'Taxa a.a.', 'Fonte', '']);
    const dates = table.getAllByRole('row').slice(1);
    expect(dates).toHaveLength(30);
    expect(within(dates[0] as HTMLElement).getByText('18/10/2026')).toBeInTheDocument();
    expect(within(dates[29] as HTMLElement).getByText('19/09/2026')).toBeInTheDocument();
    expect(screen.getByText('30 dias · 8 referências registradas')).toBeInTheDocument();
  });

  it('§5 shows a day without observation as such: no carry-forward from the day before', async () => {
    await openContract();

    expect(cells('17/10/2026')).toEqual(['17/10/2026', '—', '—', '—']);
    expect(
      dayRow('17/10/2026').getByRole('button', { name: 'Registrar preço em 17/10/2026' }),
    ).toBeInTheDocument();
    expect(cells('16/10/2026')).toEqual(['16/10/2026', '89.250,31', '9,80%', 'Manual']);
    expect(cells('15/10/2026')).toEqual(['15/10/2026', '89.128,48', '9,90%', 'B3']);
  });

  it('§5 prefers MANUAL over B3 on the same date (16/10)', async () => {
    await openContract();

    expect(cells('16/10/2026')[3]).toBe('Manual');
    expect(screen.queryByText('89.240,43')).not.toBeInTheDocument();
  });

  it('§11.2 shows the price history caption and the PU | Taxa a.a. toggle', async () => {
    await openContract();

    const card = within(screen.getByRole('region', { name: 'Histórico de preços' }));
    expect(card.getByRole('radio', { name: 'PU' })).toBeChecked();
    expect(card.getByRole('radio', { name: 'Taxa a.a.' })).not.toBeChecked();
    expect(
      card.getByText(
        'Somente referências registradas. Lacunas indicam ausência de observação, não erro de precificação.',
      ),
    ).toBeInTheDocument();
  });

  it('§5 "Ver revisões" lists every revision of both sources, newest first', async () => {
    const { user } = await openContract();

    await rowAction(user, '16/10/2026', 'Ver revisões');

    const modal = within(await screen.findByRole('dialog', { name: 'Revisões de 16/10/2026' }));
    const rows = (await modal.findAllByRole('row')).slice(1).map((row) =>
      within(row)
        .getAllByRole('cell')
        .map((cell) => cell.textContent),
    );
    expect(rows).toEqual([
      ['Manual', '2', '89.250,31', '9,80%', '17/10/2026 10:00', 'Atual'],
      ['B3', '1', '89.240,43', '9,81%', '16/10/2026 19:00', 'Atual'],
      ['Manual', '1', '89.200,90', '9,85%', '16/10/2026 18:00', '17/10/2026 10:00'],
    ]);
  });

  it('§5 a correction appends a new revision (revision 3) and is shown at once', async () => {
    const { user } = await openContract();

    await rowAction(user, '16/10/2026', 'Corrigir');
    const priceModal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    expect(priceModal.getByRole('textbox', { name: 'Data de referência' })).toHaveValue(
      '16/10/2026',
    );
    await user.click(priceModal.getByRole('radio', { name: 'Taxa a.a.' }));
    await user.type(priceModal.getByRole('textbox', { name: 'Taxa a.a. (%)' }), '9,75');
    await user.click(priceModal.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      expect(cells('16/10/2026')[2]).toBe('9,75%');
    });
    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: 'Registrar preço de referência' }),
      ).not.toBeInTheDocument();
    });
    await rowAction(user, '16/10/2026', 'Ver revisões');
    const modal = within(await screen.findByRole('dialog', { name: 'Revisões de 16/10/2026' }));
    const first = (await modal.findAllByRole('row'))[1] as HTMLElement;
    const firstCells = within(first)
      .getAllByRole('cell')
      .map((cell) => cell.textContent);
    expect(firstCells.slice(0, 2)).toEqual(['Manual', '3']);
    expect(firstCells[3]).toBe('9,75%');
    expect(firstCells[5]).toBe('Atual');
  });

  it('§5 Remover lists each current observation of the date; removing MANUAL lets B3 prevail', async () => {
    const { user } = await openContract();

    await rowAction(user, '16/10/2026', 'Remover');
    const modal = within(
      await screen.findByRole('dialog', { name: 'Remover preço de referência' }),
    );
    const manual = modal.getByRole('checkbox', { name: 'Manual: PU 89.250,31, taxa 9,80%' });
    const b3 = modal.getByRole('checkbox', { name: 'B3: PU 89.240,43, taxa 9,81%' });
    expect(manual).toBeChecked();
    expect(b3).not.toBeChecked();
    await user.click(modal.getByRole('button', { name: 'Remover' }));

    await waitFor(() => {
      expect(cells('16/10/2026')).toEqual(['16/10/2026', '89.240,43', '9,81%', 'B3']);
    });
  });

  it('§5 removes any source the user selects: both observations leave the day without a price', async () => {
    const { user } = await openContract();

    await rowAction(user, '16/10/2026', 'Remover');
    const modal = within(
      await screen.findByRole('dialog', { name: 'Remover preço de referência' }),
    );
    await user.click(modal.getByRole('checkbox', { name: 'B3: PU 89.240,43, taxa 9,81%' }));
    await user.click(modal.getByRole('button', { name: 'Remover' }));

    await waitFor(() => {
      expect(cells('16/10/2026')).toEqual(['16/10/2026', '—', '—', '—']);
    });
    expect(screen.getByText('30 dias · 7 referências registradas')).toBeInTheDocument();
  });

  it('§5 removes a B3 observation', async () => {
    const { user } = await openContract();

    await rowAction(user, '15/10/2026', 'Remover');
    const modal = within(
      await screen.findByRole('dialog', { name: 'Remover preço de referência' }),
    );
    expect(modal.getByRole('checkbox', { name: 'B3: PU 89.128,48, taxa 9,90%' })).toBeChecked();
    await user.click(modal.getByRole('button', { name: 'Remover' }));

    await waitFor(() => {
      expect(cells('15/10/2026')).toEqual(['15/10/2026', '—', '—', '—']);
    });
  });

  it('§5 after a partial failure the modal lists what is left, and a retry removes only that', async () => {
    // B3 16/10 (fixture price 10) fails once; MANUAL is removed.
    let failures = 0;
    server.use(
      http.delete(url('/reference-prices/7e000000-0000-4000-8000-000000000010'), () => {
        failures += 1;
        return failures === 1
          ? problem(500, [{ code: 'VALIDATION_ERROR', message: 'Falha ao remover.', field: null }])
          : undefined;
      }),
    );
    const { user } = await openContract();

    await rowAction(user, '16/10/2026', 'Remover');
    const modal = within(
      await screen.findByRole('dialog', { name: 'Remover preço de referência' }),
    );
    await user.click(modal.getByRole('checkbox', { name: 'B3: PU 89.240,43, taxa 9,81%' }));
    await user.click(modal.getByRole('button', { name: 'Remover' }));

    expect(await modal.findByText('Falha ao remover.')).toBeInTheDocument();
    await waitFor(() => {
      expect(
        modal.queryByRole('checkbox', { name: 'Manual: PU 89.250,31, taxa 9,80%' }),
      ).not.toBeInTheDocument();
    });
    expect(cells('16/10/2026')[3]).toBe('B3');
    expect(modal.getByRole('checkbox', { name: 'B3: PU 89.240,43, taxa 9,81%' })).toBeChecked();

    await user.click(modal.getByRole('button', { name: 'Remover' }));
    await waitFor(() => {
      expect(cells('16/10/2026')).toEqual(['16/10/2026', '—', '—', '—']);
    });
  });

  it('§5 keeps at least one observation selected', async () => {
    const { user } = await openContract();

    await rowAction(user, '15/10/2026', 'Remover');
    const modal = within(
      await screen.findByRole('dialog', { name: 'Remover preço de referência' }),
    );
    const b3 = modal.getByRole('checkbox', { name: 'B3: PU 89.128,48, taxa 9,90%' });
    await user.click(b3);

    expect(await modal.findByText('Selecione ao menos uma observação.')).toBeInTheDocument();
    expect(b3).toBeChecked();
  });
});

describe('Ativos: registrar preço (§11.2, §5)', () => {
  it('§11.2 "Registrar preço" opens the modal: contract, date, PU | Taxa a.a., one input', async () => {
    const { user } = await openContract();

    await user.click(screen.getByRole('button', { name: 'Registrar preço' }));
    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    expect(modal.getByRole('textbox', { name: 'Contrato' })).toHaveValue('DI1F28');
    expect(modal.getByRole('textbox', { name: 'Contrato' })).toHaveAttribute('readonly');
    expect(modal.getByRole('textbox', { name: 'Data de referência' })).toHaveValue('18/10/2026');
    const kind = within(modal.getByRole('radiogroup', { name: 'Forma de entrada' }));
    expect(kind.getByRole('radio', { name: 'PU' })).toBeChecked();
    expect(modal.getByRole('textbox', { name: 'PU' })).toBeInTheDocument();
    expect(modal.queryByRole('textbox', { name: 'Taxa a.a. (%)' })).not.toBeInTheDocument();
    expect(
      modal.getByText(
        'O registro não inicia um recálculo. Solicite um processamento para atualizar a carteira.',
      ),
    ).toBeInTheDocument();
  });

  it('§11.2 the "+" of an empty day opens the modal on that date', async () => {
    const { user } = await openContract();

    await user.click(screen.getByRole('button', { name: 'Registrar preço em 17/10/2026' }));

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    expect(modal.getByRole('textbox', { name: 'Data de referência' })).toHaveValue('17/10/2026');
  });

  it('§11.1 ?registrar= opens the modal on that date; saving fills the calendar', async () => {
    const { user, router } = await openContract(`${F28}?registrar=2026-10-17`);

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    expect(modal.getByRole('textbox', { name: 'Data de referência' })).toHaveValue('17/10/2026');
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '89.300,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      expect(cells('17/10/2026').slice(0, 2)).toEqual(['17/10/2026', '89.300,00']);
    });
    expect(cells('17/10/2026')[3]).toBe('Manual');
    expect(screen.getByText('30 dias · 9 referências registradas')).toBeInTheDocument();
    expect(router.state.location.search).not.toContain('registrar');
  });

  it('§4.1 rejects a value that is not a pt-BR number, without a request', async () => {
    const { user } = await openContract(`${F28}?registrar=2026-10-17`);

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    await user.type(modal.getByRole('textbox', { name: 'PU' }), 'abc');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    expect(await modal.findByText('Informe um número válido.')).toBeInTheDocument();
  });

  it('§4.1 shows the API decimal-places error on the value field (OQ-3)', async () => {
    const { user } = await openContract(`${F28}?registrar=2026-10-17`);

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '89.300,12345678901');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    expect(await modal.findByText('Use no máximo 10 casas decimais.')).toBeInTheDocument();
  });

  it('§12 shows every error the API gives for the value input (pu, rate, input_kind)', async () => {
    server.use(
      http.post(url('/reference-prices'), () =>
        problem(422, [
          { code: 'VALIDATION_ERROR', message: 'Forma de entrada inválida.', field: 'input_kind' },
          { code: 'VALIDATION_ERROR', message: 'O valor deve ser maior que zero.', field: 'pu' },
        ]),
      ),
    );
    const { user } = await openContract(`${F28}?registrar=2026-10-17`);

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '89.300,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    expect(
      await modal.findByText('O valor deve ser maior que zero.', { exact: false }),
    ).toBeInTheDocument();
    expect(modal.getByText('Forma de entrada inválida.', { exact: false })).toBeInTheDocument();
  });

  it('OQ-14 shows FUTURE_DATE on the date field', async () => {
    const { user } = await openContract(`${F28}?registrar=2026-10-19`);

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    expect(modal.getByRole('textbox', { name: 'Data de referência' })).toHaveValue('19/10/2026');
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '89.300,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    expect(await modal.findByText('A data não pode ser posterior a hoje.')).toBeInTheDocument();
  });

  it('OQ-1 shows CONTRACT_MATURED on the date field', async () => {
    server.use(
      http.post(url('/reference-prices'), () =>
        problem(422, [
          {
            code: 'CONTRACT_MATURED',
            message: 'O contrato já venceu nesta data.',
            field: 'reference_date',
          },
        ]),
      ),
    );
    const { user } = await openContract(`${F28}?registrar=2026-10-17`);

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '89.300,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    expect(await modal.findByText('O contrato já venceu nesta data.')).toBeInTheDocument();
  });
});

describe('Ativos: período do calendário (§11.2)', () => {
  it('§11.2 shows the period from the URL: one row per day, inclusive', async () => {
    await openContract(`${F28}?inicio=2026-10-01&fim=2026-10-05`);

    const table = within(screen.getByRole('table', { name: 'Calendário de preços de referência' }));
    const rows = table.getAllByRole('row').slice(1);
    expect(rows).toHaveLength(5);
    expect(within(rows[0] as HTMLElement).getByText('05/10/2026')).toBeInTheDocument();
    expect(within(rows[4] as HTMLElement).getByText('01/10/2026')).toBeInTheDocument();
    expect(screen.getByText('5 dias · 1 referência registrada')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Período' })).toHaveTextContent(
      '01/10/2026 – 05/10/2026',
    );
  });

  it('§11.2 picks the period with two clicks in the "Período" picker', async () => {
    const { user, router } = await openContract(`${F28}?inicio=2026-10-01&fim=2026-10-05`);

    await user.click(screen.getByRole('button', { name: 'Período' }));
    await user.click(await screen.findByRole('button', { name: '8 outubro 2026' }));
    await user.click(screen.getByRole('button', { name: '10 outubro 2026' }));

    await waitFor(() => {
      expect(router.state.location.search).toContain('inicio=2026-10-08');
    });
    expect(router.state.location.search).toContain('fim=2026-10-10');
    expect(await screen.findByText('3 dias · 2 referências registradas')).toBeInTheDocument();
  });

  it('§11.1 "registrar" on an older date opens the calendar on it, and the saved price stays in view', async () => {
    const { user, router } = await openContract(`${F28}?registrar=2026-08-20`);

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    expect(cells('20/08/2026')).toEqual(['20/08/2026', '—', '—', '—']);
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '88.000,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      expect(router.state.location.search).not.toContain('registrar');
    });
    expect(router.state.location.search).toContain('inicio=2026-07-22');
    expect(router.state.location.search).toContain('fim=2026-08-20');
    await waitFor(() => {
      expect(cells('20/08/2026').slice(0, 2)).toEqual(['20/08/2026', '88.000,00']);
    });
  });

  it('§11.1 cancelling a "registrar" modal keeps the period it opened on', async () => {
    const { user, router } = await openContract(`${F28}?registrar=2026-08-20`);

    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    await user.click(modal.getByRole('button', { name: 'Cancelar' }));

    await waitFor(() => {
      expect(router.state.location.search).not.toContain('registrar');
    });
    expect(router.state.location.search).toContain('fim=2026-08-20');
    expect(screen.getByText('20/08/2026', { selector: 'td' })).toBeInTheDocument();
  });

  it('§11.2 saving a price outside the period moves the period to show it', async () => {
    const { user, router } = await openContract();

    await user.click(screen.getByRole('button', { name: 'Registrar preço' }));
    const modal = within(
      await screen.findByRole('dialog', { name: 'Registrar preço de referência' }),
    );
    const date = modal.getByRole('textbox', { name: 'Data de referência' });
    await user.clear(date);
    await user.type(date, '01/09/2026');
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '88.100,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      expect(cells('01/09/2026').slice(0, 2)).toEqual(['01/09/2026', '88.100,00']);
    });
    expect(router.state.location.search).toContain('fim=2026-09-01');
  });
});

describe('Ativos: contrato, estados (§12)', () => {
  it('§11.2 switches the price history to the annual rate', async () => {
    const { user } = await openContract();

    const card = within(screen.getByRole('region', { name: 'Histórico de preços' }));
    await user.click(card.getByRole('radio', { name: 'Taxa a.a.' }));

    expect(card.getByRole('radio', { name: 'Taxa a.a.' })).toBeChecked();
    expect(card.getByRole('radio', { name: 'PU' })).not.toBeChecked();
  });

  it('§5 a contract without observations: every day "—", an empty history, 0 references', async () => {
    renderApp(`/ativos/contratos/${IDS.di1f27}`);
    await screen.findByRole('table', { name: 'Calendário de preços de referência' });

    expect(screen.getByText('30 dias · 0 referências registradas')).toBeInTheDocument();
    expect(screen.getByText('Nenhuma referência registrada neste período.')).toBeInTheDocument();
    expect(cells('18/10/2026')).toEqual(['18/10/2026', '—', '—', '—']);
  });

  it('OQ-1 the calendar of a matured contract ends on its maturity date', async () => {
    server.use(
      http.get(url('/instruments/:id'), () =>
        HttpResponse.json({
          id: IDS.di1f27,
          code: 'DI1V26',
          product_id: IDS.di1,
          product_code: 'DI1',
          maturity_date: '2026-10-01',
          last_reference: null,
          created_at: '2026-01-01T09:00:00-03:00',
        }),
      ),
    );
    renderApp(`/ativos/contratos/${IDS.di1f27}`);
    const table = within(
      await screen.findByRole('table', { name: 'Calendário de preços de referência' }),
    );

    const rows = table.getAllByRole('row').slice(1);
    expect(within(rows[0] as HTMLElement).getByText('01/10/2026')).toBeInTheDocument();
    expect(within(rows[29] as HTMLElement).getByText('02/09/2026')).toBeInTheDocument();
  });

  it('§12 shows the revisions error in the modal', async () => {
    server.use(
      http.get(url('/reference-prices/revisions'), () =>
        problem(500, [{ code: 'VALIDATION_ERROR', message: 'Serviço indisponível.', field: null }]),
      ),
    );
    const { user } = await openContract();

    await rowAction(user, '16/10/2026', 'Ver revisões');

    const modal = within(await screen.findByRole('dialog', { name: 'Revisões de 16/10/2026' }));
    expect(await modal.findByText('Serviço indisponível.')).toBeInTheDocument();
  });

  it('§12 shows "não encontrado" for an unknown contract', async () => {
    renderApp('/ativos/contratos/desconhecido');

    expect(await screen.findByText('Contrato não encontrado.')).toBeInTheDocument();
  });

  it('§12 shows the reference-price error with a retry', async () => {
    server.use(
      http.get(url('/reference-prices'), () =>
        problem(500, [{ code: 'VALIDATION_ERROR', message: 'Serviço indisponível.', field: null }]),
      ),
    );
    renderApp(F28);

    expect(await screen.findAllByText('Serviço indisponível.')).not.toHaveLength(0);
  });
});
