import { screen } from '@testing-library/react';

import { renderApp } from '@/test/render';

const modules = ['Central de Controle', 'Ativos', 'Carteira', 'Lançamentos'];

describe('AppLayout', () => {
  it('§11 lists the four modules in the sidebar, in pt-BR and in the design order', () => {
    renderApp('/carteira');

    const nav = screen.getByRole('navigation', { name: 'Módulos' });
    const links = Array.from(nav.querySelectorAll('a')).map((a) => a.getAttribute('aria-label'));
    expect(links).toEqual(modules);
  });

  it('§11.1 opens Central de Controle at the root', async () => {
    renderApp('/');

    expect(await screen.findByRole('heading', { name: 'Central de Controle' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Central de Controle' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('§11.4 navigates to Carteira and marks it as the current page', async () => {
    const { user } = renderApp('/');

    await user.click(screen.getByRole('link', { name: 'Carteira' }));

    expect(await screen.findByRole('heading', { name: 'Carteira' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Carteira' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Ativos' })).not.toHaveAttribute('aria-current');
  });

  it('§11 collapses the sidebar and keeps every module reachable by name', async () => {
    const { user } = renderApp('/ativos');

    await user.click(screen.getByRole('button', { name: 'Recolher navegação' }));

    expect(screen.getByRole('button', { name: 'Expandir navegação' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(screen.queryByText('BACKOFFICE')).not.toBeInTheDocument();
    for (const name of modules) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument();
    }
  });

  it('§11 remembers the collapsed sidebar across visits', async () => {
    const first = renderApp('/ativos');
    await first.user.click(screen.getByRole('button', { name: 'Recolher navegação' }));
    first.unmount();

    renderApp('/ativos');

    expect(screen.getByRole('button', { name: 'Expandir navegação' })).toBeInTheDocument();
  });

  it('§11 shows a pt-BR page for an unknown address', async () => {
    renderApp('/nao-existe');

    expect(
      await screen.findByRole('heading', { name: 'Página não encontrada' }),
    ).toBeInTheDocument();
  });
});
