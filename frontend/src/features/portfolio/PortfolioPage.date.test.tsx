import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';

import { todayInSaoPaulo } from '@/shared/format';
import { renderApp } from '@/test/render';

import { openCarteira } from './portfolioPage.support';

// The notifications store is module-global: a notice of one test must not stay for the next.
afterEach(() => {
  notifications.clean();
});

describe('Carteira (§11.4)', () => {
  it('§11.4 picking a date in the calendar loads that date and puts it in the URL', async () => {
    const { user, router } = await openCarteira('2026-10-15');

    await user.click(screen.getByRole('button', { name: /Data de avaliação/ }));
    await user.click(await screen.findByRole('button', { name: '16 outubro 2026' }));

    expect(router.state.location.search).toBe('?date=2026-10-16');
    const cash = await screen.findByRole('group', { name: 'Saldo em caixa' });
    expect(within(cash).getByText('R$ 506.059,27')).toBeInTheDocument();
  });

  it('§11.4 OQ-14 falls back to today for a future date, in the view and in the URL', async () => {
    const { router } = renderApp('/carteira?date=2999-01-01');

    const [year, month, day] = todayInSaoPaulo().split('-');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Data de avaliação/ })).toHaveTextContent(
        `${day ?? ''}/${month ?? ''}/${year ?? ''}`,
      );
    });
    expect(router.state.location.search).toBe(`?date=${todayInSaoPaulo()}`);
    // Not silently: the user is told why the date changed.
    expect(
      await screen.findByText('A data 01/01/2999 não pode ser posterior a hoje e foi ignorada.'),
    ).toBeInTheDocument();
  });
});
