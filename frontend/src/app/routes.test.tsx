import { screen } from '@testing-library/react';

import { IDS } from '@/api/mocks/fixtures';
import { renderApp } from '@/test/render';

import { assetLinks } from './paths';

describe('routes', () => {
  it('§11.2 serves the product page under Ativos', async () => {
    renderApp(assetLinks.product(IDS.di1));

    expect(await screen.findByRole('heading', { name: 'Produto' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ativos' })).toHaveAttribute('aria-current', 'page');
  });

  it('§11.2 serves the contract page under Ativos, with the "registrar" deep link', async () => {
    const { router } = renderApp(assetLinks.contract(IDS.di1f29, { register: '2026-10-16' }));

    expect(await screen.findByRole('heading', { name: 'Contrato' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ativos' })).toHaveAttribute('aria-current', 'page');
    expect(router.state.location.search).toBe('?registrar=2026-10-16');
  });

  it('§11 shows the not-found page for an unknown Ativos path', async () => {
    renderApp('/ativos/desconhecido');

    expect(await screen.findByText(/não encontrada/i)).toBeInTheDocument();
  });
});
