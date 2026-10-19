import { screen, waitFor, within } from '@testing-library/react';

import { IDS } from '@/api/mocks/fixtures';
import { renderApp } from '@/test/render';

import { assetLinks, paths } from './paths';

// These tests check the routing only: which route matches and with which parameters. What
// each page shows belongs to its feature's tests, so the screens can replace their
// placeholders without touching this file.

type AppRouter = ReturnType<typeof renderApp>['router'];

/** The sidebar: a page may add its own "Ativos" link (the breadcrumb). */
const modules = () => within(screen.getByRole('navigation', { name: 'Módulos' }));

function matched(router: AppRouter) {
  const match = router.state.matches.at(-1);
  return { path: match?.route.path, params: match?.params };
}

describe('routes', () => {
  it('§11.2 serves the product page under Ativos', async () => {
    const { router } = renderApp(assetLinks.product(IDS.di1));

    await waitFor(() => {
      expect(matched(router)).toEqual({
        path: paths.assetProduct,
        params: { productId: IDS.di1 },
      });
    });
    expect(modules().getByRole('link', { name: 'Ativos' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByText(/não encontrada/i)).not.toBeInTheDocument();
  });

  it('§11.2 serves the contract page under Ativos, with the "registrar" deep link', async () => {
    const { router } = renderApp(assetLinks.contract(IDS.di1f29, { register: '2026-10-16' }));

    await waitFor(() => {
      expect(matched(router)).toEqual({
        path: paths.assetContract,
        params: { instrumentId: IDS.di1f29 },
      });
    });
    expect(router.state.location.search).toBe('?registrar=2026-10-16');
    expect(modules().getByRole('link', { name: 'Ativos' })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByText(/não encontrada/i)).not.toBeInTheDocument();
  });

  it('§11 shows the not-found page for an unknown Ativos path', async () => {
    renderApp('/ativos/desconhecido');

    expect(await screen.findByText(/não encontrada/i)).toBeInTheDocument();
  });
});
