import { act, screen, waitFor, within } from '@testing-library/react';
import { delay, http, HttpResponse } from 'msw';

import { IDS, instrumentTypes, products } from '@/test/msw/fixtures';
import { problem, url } from '@/test/helpers';
import { server } from '@/test/msw/server';
import { renderRoute } from '@/test/render';

// Expected values come from the fixtures (src/test/msw/fixtures.ts): one instrument type
// (Futuros), one product (DI1) with four contracts.

/**
 * The search is the backend's (OQ-33): this answers DI1 to no search or "juros" (its class) and
 * nothing to any other, and records each search the screen sent.
 */
function serveSearch() {
  const searches: (string | null)[] = [];
  server.use(
    http.get(url('/products'), ({ request }) => {
      const search = new URL(request.url).searchParams.get('search');
      searches.push(search);
      return HttpResponse.json({ items: !search || search === 'juros' ? products : [] });
    }),
  );
  return searches;
}

async function openCatalogue(route = '/ativos') {
  const result = renderRoute(route);
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
    const searches = serveSearch();
    const { user, router } = await openCatalogue();

    const search = screen.getByRole('textbox', { name: 'Buscar produtos' });
    expect(search).toHaveAttribute('placeholder', 'Buscar por código, produto ou classe...');
    await user.type(search, 'juros');
    // Once the typing settles (SearchInput), the search reaches the URL and the request.
    await waitFor(() => {
      expect(router.state.location.search).toContain('busca=juros');
    });
    // The request proves the page rendered the new search: only then is the box cleared, or a
    // late render would put "juros" back under the typing (the router updates in a transition).
    await waitFor(() => {
      expect(searches).toContain('juros');
    });
    expect(await screen.findByText('1 produto encontrado')).toBeInTheDocument();

    await user.clear(search);
    await user.type(search, 'xyz');
    expect(await screen.findByText('0 produtos encontrados')).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: /DI1/ })).not.toBeInTheDocument();
    expect(searches.at(-1)).toBe('xyz');
  });

  it('§11.2 reads the search from the URL', async () => {
    const searches = serveSearch();
    await openCatalogue('/ativos?busca=xyz');

    expect(screen.getByRole('textbox', { name: 'Buscar produtos' })).toHaveValue('xyz');
    expect(await screen.findByText('0 produtos encontrados')).toBeInTheDocument();
    expect(searches).toEqual(['xyz']);
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
    serveSearch();
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
    renderRoute('/ativos');

    expect(await screen.findByText('Serviço indisponível.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument();
  });

  it('§11.2 says so when the API returns no instrument type', async () => {
    server.use(http.get(url('/instrument-types'), () => HttpResponse.json({ items: [] })));
    renderRoute('/ativos');

    expect(await screen.findByText('Nenhum tipo de instrumento cadastrado.')).toBeInTheDocument();
  });
});
