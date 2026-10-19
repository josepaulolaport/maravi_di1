import { act, screen, within } from '@testing-library/react';
import { delay, http, HttpResponse } from 'msw';

import { IDS, instrumentTypes } from '@/api/mocks/fixtures';
import { problem, url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { renderApp } from '@/test/render';

// Expected values come from the fixture scenario (src/api/mocks/fixtures.ts): one instrument
// type (Futuros), one product (DI1) with four contracts.

async function openCatalogue(route = '/ativos') {
  const result = renderApp(route);
  await screen.findByRole('table', { name: 'Produtos' });
  return result;
}

describe('Ativos: catálogo (§11.2)', () => {
  it('§11.2 shows the instrument types the API returns as tabs, and nothing else', async () => {
    await openCatalogue();

    const tabs = screen.getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs).toEqual(['Futuros']);
    expect(screen.getByRole('tab', { name: 'Futuros' })).toHaveAttribute('aria-selected', 'true');
  });

  it('§11.2 falls back to the first tab when ?tipo= names no type the API returns', async () => {
    await openCatalogue('/ativos?tipo=OPTION');

    expect(screen.getByRole('tab', { name: 'Futuros' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('1 produto encontrado')).toBeInTheDocument();
  });

  it('§11.2 lists the real products: code, name, class and number of contracts', async () => {
    await openCatalogue();

    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(headers).toEqual(['Código', 'Produto', 'Classe', 'Contratos', '']);
    const row = within(screen.getByRole('row', { name: /DI1/ }));
    expect(row.getByText('DI1')).toBeInTheDocument();
    expect(
      row.getByText('Futuro de Taxa Média de Depósitos Interfinanceiros de Um Dia'),
    ).toBeInTheDocument();
    expect(row.getByText('Futuros de Taxa de Juros')).toBeInTheDocument();
    expect(row.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('1 produto encontrado')).toBeInTheDocument();
  });

  it('§11.2 searches by code, product or class, and keeps the search in the URL', async () => {
    const { user, router } = await openCatalogue();

    const search = screen.getByRole('textbox', { name: 'Buscar produtos' });
    expect(search).toHaveAttribute('placeholder', 'Buscar por código, produto ou classe...');
    await user.type(search, 'juros');
    expect(await screen.findByText('1 produto encontrado')).toBeInTheDocument();
    expect(router.state.location.search).toContain('busca=juros');

    await user.clear(search);
    await user.type(search, 'xyz');
    expect(await screen.findByText('0 produtos encontrados')).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: /DI1/ })).not.toBeInTheDocument();
  });

  it('§11.2 reads the search from the URL', async () => {
    await openCatalogue('/ativos?busca=xyz');

    expect(screen.getByRole('textbox', { name: 'Buscar produtos' })).toHaveValue('xyz');
    expect(await screen.findByText('0 produtos encontrados')).toBeInTheDocument();
  });

  it('§11.2 opens the product page from its row', async () => {
    const { user, router } = await openCatalogue();

    await user.click(screen.getByRole('link', { name: 'Abrir produto DI1' }));

    expect(router.state.location.pathname).toBe(`/ativos/produtos/${IDS.di1}`);
  });

  it("§11.2 a new tab never shows the previous type's products while it loads", async () => {
    server.use(
      http.get(url('/instrument-types'), () =>
        HttpResponse.json({
          items: [...instrumentTypes, { id: 2, code: 'OPTION', name: 'Opções', asset_classes: [] }],
        }),
      ),
      http.get(url('/products'), async ({ request }) => {
        if (new URL(request.url).searchParams.get('instrument_type') === 'OPTION') {
          await delay('infinite');
        }
        return undefined;
      }),
    );
    const { user } = await openCatalogue();

    await user.click(screen.getByRole('tab', { name: 'Opções' }));

    expect(await screen.findByRole('status', { name: 'Carregando produtos' })).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: /DI1/ })).not.toBeInTheDocument();
  });

  it('§11.2 the search box follows the URL on navigation (back, links)', async () => {
    const { router } = await openCatalogue('/ativos?busca=juros');
    const search = screen.getByRole('textbox', { name: 'Buscar produtos' });

    await act(() => router.navigate('/ativos?busca=xyz'));
    expect(search).toHaveValue('xyz');
    expect(await screen.findByText('0 produtos encontrados')).toBeInTheDocument();

    await act(() => router.navigate(-1));
    expect(search).toHaveValue('juros');
  });

  it('§12 shows the API error with a retry', async () => {
    server.use(
      http.get(url('/instrument-types'), () =>
        problem(500, [{ code: 'VALIDATION_ERROR', message: 'Serviço indisponível.', field: null }]),
      ),
    );
    renderApp('/ativos');

    expect(await screen.findByText('Serviço indisponível.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument();
  });

  it('§11.2 says so when the API returns no instrument type', async () => {
    server.use(http.get(url('/instrument-types'), () => HttpResponse.json({ items: [] })));
    renderApp('/ativos');

    expect(await screen.findByText('Nenhum tipo de instrumento cadastrado.')).toBeInTheDocument();
  });
});
