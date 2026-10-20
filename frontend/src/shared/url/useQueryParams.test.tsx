import { notifications } from '@mantine/notifications';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';

import { AppProviders } from '@/app/providers';
import { TEST_TODAY } from '@/test/msw/fixtures';
import { createQueryClient } from '@/app/queryClient';

import { dateParam, enumParam, textParam, useQueryParams, withFallback } from './useQueryParams';

afterEach(() => {
  notifications.clean();
});

function useProbe() {
  return useQueryParams(
    {
      inicio: dateParam({ max: TEST_TODAY }),
      fim: withFallback(dateParam({ max: TEST_TODAY }), TEST_TODAY),
      escopo: withFallback(enumParam({ CASH: 'caixa', ALL: 'tudo' }), 'ALL'),
      busca: textParam,
    },
    (v) => ({ inicio: v.inicio !== null && v.inicio <= v.fim ? v.inicio : null }),
  );
}

function Probe() {
  const { values, set } = useProbe();
  return (
    <>
      <output aria-label="values">{JSON.stringify(values)}</output>
      <button
        onClick={() => {
          set({ busca: '' });
        }}
      >
        clear
      </button>
      <button
        onClick={() => {
          set({ inicio: '2026-10-14', fim: '2026-10-15', escopo: 'CASH' }, { push: true });
        }}
      >
        range
      </button>
    </>
  );
}

function renderAt(url: string) {
  const router = createMemoryRouter([{ path: '/', element: <Probe /> }], {
    initialEntries: [url],
  });
  render(
    <AppProviders queryClient={createQueryClient()}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

const shown = () =>
  JSON.parse(screen.getByRole('status', { name: 'values' }).textContent) as Record<string, unknown>;

describe('useQueryParams (URL state)', () => {
  it('reads each key with its parser, and the fallback when a key is absent', () => {
    renderAt('/?inicio=2026-10-14&escopo=caixa&busca=DI1');
    expect(shown()).toEqual({
      inicio: '2026-10-14',
      fim: TEST_TODAY,
      escopo: 'CASH',
      busca: 'DI1',
    });
  });

  it('corrects an invalid value in the URL with a replace, never a new history entry', async () => {
    const router = renderAt('/?fim=2026-02-31&escopo=xyz&busca=DI1');
    await waitFor(() => {
      expect(router.state.location.search).toBe(`?fim=${TEST_TODAY}&escopo=tudo&busca=DI1`);
    });
    expect(router.state.historyAction).toBe('REPLACE');
  });

  it('drops a value its refinement rejects (a start after the end)', async () => {
    const router = renderAt('/?inicio=2026-10-16&fim=2026-10-15');
    expect(shown()).toMatchObject({ inicio: null, fim: '2026-10-15' });
    await waitFor(() => {
      expect(router.state.location.search).toBe('?fim=2026-10-15');
    });
  });

  it('OQ-14 reports a future date in the link, and drops it', async () => {
    const router = renderAt('/?inicio=2999-01-01');
    expect(
      await screen.findByText('A data 01/01/2999 não pode ser posterior a hoje e foi ignorada.'),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(router.state.location.search).toBe('');
    });
  });

  it('writes with a replace by default and with a push when asked; null and "" remove a key', async () => {
    const router = renderAt('/?busca=DI1');
    fireEvent.click(screen.getByRole('button', { name: 'clear' }));
    await waitFor(() => {
      expect(router.state.location.search).toBe('');
    });
    expect(router.state.historyAction).toBe('REPLACE');

    fireEvent.click(screen.getByRole('button', { name: 'range' }));
    await waitFor(() => {
      expect(router.state.location.search).toBe('?inicio=2026-10-14&fim=2026-10-15&escopo=caixa');
    });
    expect(router.state.historyAction).toBe('PUSH');
  });
});
