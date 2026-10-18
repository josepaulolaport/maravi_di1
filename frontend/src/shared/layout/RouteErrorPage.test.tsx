import { QueryClient } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';

import { AppProviders } from '@/app/providers';

import { RouteErrorPage } from './RouteErrorPage';

function Broken(): never {
  throw new Error('falha de renderização');
}

describe('RouteErrorPage', () => {
  it('§11 shows a pt-BR message instead of a blank page when a screen throws', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const router = createMemoryRouter([
      { path: '/', element: <Broken />, errorElement: <RouteErrorPage /> },
    ]);

    render(
      <AppProviders queryClient={new QueryClient()}>
        <RouterProvider router={router} />
      </AppProviders>,
    );

    expect(await screen.findByRole('heading', { name: 'Algo deu errado' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Voltar ao início' })).toHaveAttribute('href', '/');
  });
});
