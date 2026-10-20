import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import type { Instrument, LastReference } from '@/api/contract';
import { IDS, instruments, PRICES, products } from '@/test/msw/fixtures';
import {
  fieldError,
  problem,
  url,
  type User,
  cellTexts,
  rowContaining,
  rowElement,
} from '@/test/helpers';
import { server } from '@/test/msw/server';
import { renderRoute } from '@/test/render';

// Expected values come from the fixtures (src/test/msw/fixtures.ts). The API returns
// `last_reference: null` for every contract for now (OQ-33 item 4); the test that shows an
// observation answers it itself.

async function openProduct() {
  const result = renderRoute(`/ativos/produtos/${IDS.di1}`);
  await screen.findByRole('heading', { name: 'DI1' });
  await screen.findByRole('table', { name: 'Contratos' });
  return result;
}

describe('Ativos: produto (§11.2)', () => {
  it('§11.2 shows the breadcrumb, the title with its class and the product name', async () => {
    await openProduct();

    const breadcrumb = within(screen.getByRole('navigation', { name: 'Trilha' }));
    expect(breadcrumb.getByRole('link', { name: 'Ativos' })).toHaveAttribute('href', '/ativos');
    expect(breadcrumb.getByText('DI1')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('Futuros de Taxa de Juros')).toBeInTheDocument();
    expect(
      screen.getByText('Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia'),
    ).toBeInTheDocument();
  });

  it('§11.2 shows no specification card (user, 2026-10-18)', async () => {
    await openProduct();

    expect(screen.queryByRole('region', { name: 'Especificações' })).not.toBeInTheDocument();
    expect(screen.queryByText('Valor de referência')).not.toBeInTheDocument();
    expect(screen.queryByText('Contagem de dias')).not.toBeInTheDocument();
    expect(screen.queryByText('Precificação')).not.toBeInTheDocument();
  });

  it('§11.2 §5 lists each contract with its latest observation next to its own date', async () => {
    // The API fills `last_reference` only once Prices exposes it (OQ-33 item 4).
    const observed: Record<string, LastReference> = {
      DI1F28: {
        reference_date: '2026-10-16',
        pu: '89250.3147019396',
        rate: '0.0980',
        source: 'MANUAL',
      },
      DI1F29: {
        reference_date: '2026-10-15',
        pu: '80206.1333187932',
        rate: '0.1045',
        source: 'MANUAL',
      },
    };
    server.use(
      http.get(url('/instruments'), () =>
        HttpResponse.json({
          items: instruments.map((i) => ({ ...i, last_reference: observed[i.code] ?? null })),
        }),
      ),
    );
    await openProduct();

    const headers = within(screen.getByRole('table', { name: 'Contratos' }))
      .getAllByRole('columnheader')
      .map((th) => th.textContent);
    expect(headers).toEqual(['Contrato', 'Vencimento', 'Último PU', 'Taxa a.a.', 'Data ref.', '']);
    expect(cellTexts(rowElement('DI1F28')).slice(0, 5)).toEqual([
      'DI1F28',
      '03/01/2028',
      '89.250,31',
      '9,8000%',
      '16/10/2026',
    ]);
    expect(cellTexts(rowElement('DI1F29')).slice(0, 5)).toEqual([
      'DI1F29',
      '02/01/2029',
      '80.206,13',
      '10,4500%',
      '15/10/2026',
    ]);
    expect(screen.getByText('4 contratos cadastrados')).toBeInTheDocument();
  });

  it('§5 OQ-33 shows a contract without a last reference as unavailable, never as zero', async () => {
    await openProduct();

    // The API returns `last_reference: null` for every contract for now (OQ-33 item 4).
    expect(cellTexts(rowElement('DI1F27')).slice(0, 5)).toEqual([
      'DI1F27',
      '04/01/2027',
      '—',
      '—',
      '—',
    ]);
    expect(cellTexts(rowElement('DI1F28')).slice(0, 5)).toEqual([
      'DI1F28',
      '03/01/2028',
      '—',
      '—',
      '—',
    ]);
  });

  it('§11.2 searches contracts by code and links each to its page', async () => {
    // The search is the backend's (OQ-33): "f29" answers DI1F29 only.
    const searches: (string | null)[] = [];
    server.use(
      http.get(url('/instruments'), ({ request }) => {
        const search = new URL(request.url).searchParams.get('search');
        searches.push(search);
        return HttpResponse.json({
          items: search === 'f29' ? instruments.filter((i) => i.code === 'DI1F29') : instruments,
        });
      }),
    );
    const { user, router } = await openProduct();

    const search = screen.getByRole('textbox', { name: 'Buscar contratos' });
    expect(search).toHaveAttribute('placeholder', 'Buscar contrato por código...');
    await user.type(search, 'f29');
    await waitFor(() => {
      expect(screen.queryByText('DI1F28', { selector: 'td *' })).not.toBeInTheDocument();
    });
    expect(screen.getByText('DI1F29', { selector: 'td *' })).toBeInTheDocument();
    expect(router.state.location.search).toContain('busca=f29');
    expect(searches.at(-1)).toBe('f29');

    await user.click(screen.getByRole('link', { name: 'Abrir contrato DI1F29' }));
    expect(router.state.location.pathname).toBe(`/ativos/contratos/${IDS.di1f29}`);
  });

  it('§3 creates a contract and shows the API field errors on their fields', async () => {
    // The API's answers, in turn: the missing fields, a duplicate code, then the new contract,
    // which the list and the product's count include from then on.
    const created: Instrument = {
      id: '9a000004-0000-4000-8000-000000000004',
      code: 'DI1F31',
      product_id: IDS.di1,
      product_code: 'DI1',
      maturity_date: '2031-01-02',
      last_reference: null,
      created_at: '2026-10-18T12:00:00-03:00',
    };
    const answers = [
      () =>
        problem(422, [
          fieldError('VALIDATION_ERROR', 'Informe o código do contrato.', 'code'),
          fieldError('VALIDATION_ERROR', 'Informe o vencimento.', 'maturity_date'),
        ]),
      () =>
        problem(422, [
          fieldError('VALIDATION_ERROR', 'Já existe um contrato com este código.', 'code'),
        ]),
      () => {
        listed.push(created);
        return HttpResponse.json(created, { status: 201 });
      },
    ];
    const listed = [...instruments];
    const bodies: unknown[] = [];
    server.use(
      http.get(url('/instruments'), () => HttpResponse.json({ items: listed })),
      http.get(url('/products/:id'), () =>
        HttpResponse.json({ ...products[0], instrument_count: listed.length }),
      ),
      http.post(url('/instruments'), async ({ request }) => {
        bodies.push(await request.json());
        return (answers[bodies.length - 1] as () => Response)();
      }),
    );
    const { user } = await openProduct();

    await user.click(screen.getByRole('button', { name: 'Novo contrato' }));
    const modal = within(await screen.findByRole('dialog', { name: 'Novo contrato' }));
    await user.click(modal.getByRole('button', { name: 'Cadastrar contrato' }));
    expect(await modal.findByText('Informe o código do contrato.')).toBeInTheDocument();
    expect(modal.getByText('Informe o vencimento.')).toBeInTheDocument();

    await user.type(modal.getByRole('textbox', { name: 'Código' }), 'DI1F28');
    await user.type(modal.getByRole('textbox', { name: 'Vencimento' }), '02/01/2031');
    await user.click(modal.getByRole('button', { name: 'Cadastrar contrato' }));
    expect(await modal.findByText('Já existe um contrato com este código.')).toBeInTheDocument();

    // Editing the field drops its server message at once, before the next submit.
    await user.clear(modal.getByRole('textbox', { name: 'Código' }));
    expect(modal.queryByText('Já existe um contrato com este código.')).not.toBeInTheDocument();
    await user.type(modal.getByRole('textbox', { name: 'Código' }), 'DI1F31');
    await user.click(modal.getByRole('button', { name: 'Cadastrar contrato' }));

    expect(await screen.findByText('DI1F31', { selector: 'td *' })).toBeInTheDocument();
    expect(cellTexts(rowElement('DI1F31')).slice(0, 5)).toEqual([
      'DI1F31',
      '02/01/2031',
      '—',
      '—',
      '—',
    ]);
    expect(await screen.findByText('5 contratos cadastrados')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'Novo contrato' })).not.toBeInTheDocument();
    });
    expect(bodies.at(-1)).toEqual({
      product_id: IDS.di1,
      code: 'DI1F31',
      maturity_date: '2031-01-02',
    });
  });

  it('§12 shows "não encontrado" for an unknown product', async () => {
    renderRoute('/ativos/produtos/desconhecido');

    expect(await screen.findByText('Produto não encontrado.')).toBeInTheDocument();
  });

  it('§11.2 says so when the product has no contract', async () => {
    server.use(http.get(url('/instruments'), () => HttpResponse.json({ items: [] })));
    renderRoute(`/ativos/produtos/${IDS.di1}`);

    expect(await screen.findByText('Nenhum contrato encontrado.')).toBeInTheDocument();
  });
});

/** Records the body of every price save, then lets the default handler answer it. */
function recordSaves() {
  const bodies: unknown[] = [];
  server.use(
    http.post(url('/reference-prices'), async ({ request }) => {
      bodies.push(await request.clone().json());
      return undefined;
    }),
  );
  return bodies;
}

async function rowMenu(user: User, code: string, item: string) {
  await user.click(rowContaining(code).getByRole('button', { name: `Ações de ${code}` }));
  await user.click(await screen.findByRole('menuitem', { name: item }));
}

const priceDialog = async () =>
  within(await screen.findByRole('dialog', { name: 'Registrar preço de referência' }));

describe('Ativos: preços na lista de contratos (§11.2, §5, OQ-48 item 1)', () => {
  beforeEach(() => {
    notifications.clean();
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-18T12:00:00-03:00'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('§11.2 "Registrar preço" above the list asks for the contract, then saves its price', async () => {
    const saves = recordSaves();
    const { user, router } = await openProduct();

    await user.click(screen.getByRole('button', { name: 'Registrar preço' }));
    const modal = await priceDialog();
    expect(modal.getByRole('combobox', { name: 'Contrato' })).toHaveValue('');
    expect(modal.getByRole('textbox', { name: 'Data de referência' })).toHaveValue('18/10/2026');
    await user.click(modal.getByRole('combobox', { name: 'Contrato' }));
    await user.click(await screen.findByRole('option', { name: 'DI1F29', hidden: true }));
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '80.300,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: 'Registrar preço de referência' }),
      ).not.toBeInTheDocument();
    });
    expect(saves).toEqual([
      { asset_id: IDS.di1f29, reference_date: '2026-10-18', input_kind: 'PU', pu: '80300.00' },
    ]);
    expect(router.state.location.pathname).toBe(`/ativos/produtos/${IDS.di1}`);
  });

  it('§11.2 asks for the contract before any request', async () => {
    const saves = recordSaves();
    const { user } = await openProduct();

    await user.click(screen.getByRole('button', { name: 'Registrar preço' }));
    const modal = await priceDialog();
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '80.300,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    expect(await modal.findByText('Selecione o contrato.')).toBeInTheDocument();
    expect(saves).toEqual([]);
  });

  it('OQ-15 shows the API field errors on their fields, as on the contract page', async () => {
    server.use(
      http.post(url('/reference-prices'), () =>
        problem(422, [
          fieldError('CONTRACT_MATURED', 'O contrato já venceu nesta data.', 'reference_date'),
        ]),
      ),
    );
    const { user } = await openProduct();

    await rowMenu(user, 'DI1F27', 'Registrar preço');
    const modal = await priceDialog();
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '99.000,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));

    expect(await modal.findByText('O contrato já venceu nesta data.')).toBeInTheDocument();
  });

  it('§11.2 each row has a menu; "Registrar preço" opens the form with that contract, without leaving', async () => {
    const saves = recordSaves();
    const { user, router } = await openProduct();

    await user.click(rowContaining('DI1F28').getByRole('button', { name: 'Ações de DI1F28' }));
    expect((await screen.findAllByRole('menuitem')).map((item) => item.textContent)).toEqual([
      'Registrar preço',
      'Remover preço',
    ]);
    await user.click(screen.getByRole('menuitem', { name: 'Registrar preço' }));
    const modal = await priceDialog();
    expect(modal.getByRole('combobox', { name: 'Contrato' })).toHaveValue('DI1F28');
    expect(router.state.location.pathname).toBe(`/ativos/produtos/${IDS.di1}`);

    await user.click(modal.getByRole('radio', { name: 'Taxa a.a.' }));
    await user.type(modal.getByRole('textbox', { name: 'Taxa a.a. (%)' }), '9,85');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));
    await waitFor(() => {
      expect(saves).toEqual([
        { asset_id: IDS.di1f28, reference_date: '2026-10-18', input_kind: 'RATE', rate: '0.0985' },
      ]);
    });
  });

  it('§5 "Remover preço" picks a date, then lists its sources to remove', async () => {
    const deleted: string[] = [];
    server.use(
      http.delete(url('/reference-prices/:id'), ({ params }) => {
        deleted.push(params.id as string);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { user } = await openProduct();

    await rowMenu(user, 'DI1F28', 'Remover preço');
    const pick = within(await screen.findByRole('dialog', { name: 'Remover preço de referência' }));
    expect(pick.getByRole('textbox', { name: 'Contrato' })).toHaveValue('DI1F28');
    await user.type(pick.getByRole('textbox', { name: 'Data de referência' }), '16/10/2026');
    await user.click(pick.getByRole('button', { name: 'Continuar' }));

    const remove = within(
      await screen.findByRole('dialog', { name: 'Remover preço de referência' }),
    );
    expect(await remove.findByText('Preços de 16/10/2026:')).toBeInTheDocument();
    expect(remove.getByRole('checkbox', { name: /^Manual:/ })).toBeChecked();
    expect(remove.getByRole('checkbox', { name: /^B3:/ })).not.toBeChecked();
    await user.click(remove.getByRole('button', { name: 'Remover' }));

    await waitFor(() => {
      expect(deleted).toEqual([PRICES.f28_1016_manual.id]);
    });
  });

  it("§5 removing a date's last price closes the form and confirms it", async () => {
    // From the delete on, the API lists no price on 16/10 for DI1F28.
    let removed = false;
    server.use(
      http.delete(url('/reference-prices/:id'), () => {
        removed = true;
        return new HttpResponse(null, { status: 204 });
      }),
      http.get(url('/reference-prices'), ({ request }) => {
        const params = new URL(request.url).searchParams;
        const day = {
          reference_date: '2026-10-16',
          preferred: PRICES.f28_1016_manual,
          sources: [PRICES.f28_1016_manual],
        };
        return HttpResponse.json({
          items: !removed && params.get('start_date') === '2026-10-16' ? [day] : [],
        });
      }),
    );
    const { user } = await openProduct();

    await rowMenu(user, 'DI1F28', 'Remover preço');
    const pick = within(await screen.findByRole('dialog', { name: 'Remover preço de referência' }));
    await user.type(pick.getByRole('textbox', { name: 'Data de referência' }), '16/10/2026');
    await user.click(pick.getByRole('button', { name: 'Continuar' }));
    const remove = within(
      await screen.findByRole('dialog', { name: 'Remover preço de referência' }),
    );
    await remove.findByText('Preços de 16/10/2026:');
    await user.click(remove.getByRole('button', { name: 'Remover' }));

    expect(await screen.findAllByText('Preço de referência removido.')).toHaveLength(1);
    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: 'Remover preço de referência' }),
      ).not.toBeInTheDocument();
    });
    expect(screen.queryByText('Nenhum preço registrado nesta data.')).not.toBeInTheDocument();
  });

  it('§12 a failed price lookup shows the API message, and "Continuar" tries again', async () => {
    let calls = 0;
    server.use(
      http.get(url('/reference-prices'), () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json(
              {
                type: 'about:blank',
                title: 'Serviço indisponível. Tente novamente.',
                status: 503,
                detail: 'Serviço indisponível. Tente novamente.',
              },
              { status: 503, headers: { 'Content-Type': 'application/problem+json' } },
            )
          : HttpResponse.json({ items: [] });
      }),
    );
    const { user } = await openProduct();

    await rowMenu(user, 'DI1F28', 'Remover preço');
    const pick = within(await screen.findByRole('dialog', { name: 'Remover preço de referência' }));
    await user.type(pick.getByRole('textbox', { name: 'Data de referência' }), '17/10/2026');
    await user.click(pick.getByRole('button', { name: 'Continuar' }));
    expect(await pick.findByText('Serviço indisponível. Tente novamente.')).toBeInTheDocument();

    await user.click(pick.getByRole('button', { name: 'Continuar' }));
    expect(await pick.findByText('Nenhum preço registrado nesta data.')).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it('OQ-1 a matured contract opens the form on its maturity date, not after it', async () => {
    server.use(
      http.get(url('/instruments'), () =>
        HttpResponse.json({
          items: instruments.map((i) =>
            i.code === 'DI1F27' ? { ...i, maturity_date: '2026-10-01' } : i,
          ),
        }),
      ),
    );
    const { user } = await openProduct();

    await rowMenu(user, 'DI1F27', 'Registrar preço');
    const modal = await priceDialog();

    expect(modal.getByRole('textbox', { name: 'Data de referência' })).toHaveValue('01/10/2026');
  });

  it('OQ-1 choosing a matured contract drops a date after its maturity, and says why', async () => {
    server.use(
      http.get(url('/instruments'), () =>
        HttpResponse.json({
          items: instruments.map((i) =>
            i.code === 'DI1F27' ? { ...i, maturity_date: '2026-10-01' } : i,
          ),
        }),
      ),
    );
    const { user } = await openProduct();

    await user.click(screen.getByRole('button', { name: 'Registrar preço' }));
    const modal = await priceDialog();
    await user.click(modal.getByRole('combobox', { name: 'Contrato' }));
    await user.click(await screen.findByRole('option', { name: 'DI1F27', hidden: true }));

    expect(modal.getByRole('textbox', { name: 'Data de referência' })).toHaveValue('');
    expect(modal.getByText('O contrato já venceu nesta data.')).toBeInTheDocument();
  });

  it('OQ-15 an API error of one contract goes away when another contract is chosen', async () => {
    server.use(
      http.post(url('/reference-prices'), () =>
        problem(422, [
          fieldError('CONTRACT_MATURED', 'O contrato já venceu nesta data.', 'reference_date'),
        ]),
      ),
    );
    const { user } = await openProduct();

    await rowMenu(user, 'DI1F27', 'Registrar preço');
    const modal = await priceDialog();
    await user.type(modal.getByRole('textbox', { name: 'PU' }), '99.000,00');
    await user.click(modal.getByRole('button', { name: 'Salvar' }));
    await modal.findByText('O contrato já venceu nesta data.');

    await user.click(modal.getByRole('combobox', { name: 'Contrato' }));
    await user.click(await screen.findByRole('option', { name: 'DI1F29', hidden: true }));

    expect(modal.queryByText('O contrato já venceu nesta data.')).not.toBeInTheDocument();
  });

  it('§5 "Remover preço" on a date without a price says so', async () => {
    const { user } = await openProduct();

    await rowMenu(user, 'DI1F28', 'Remover preço');
    const pick = within(await screen.findByRole('dialog', { name: 'Remover preço de referência' }));
    await user.type(pick.getByRole('textbox', { name: 'Data de referência' }), '17/10/2026');
    await user.click(pick.getByRole('button', { name: 'Continuar' }));

    expect(await pick.findByText('Nenhum preço registrado nesta data.')).toBeInTheDocument();
  });
});
