import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import { pnlSeries } from '@/test/msw/fixtures';
import { url } from '@/test/msw/handlers';
import { server } from '@/test/msw/server';
import { renderApp, renderUi } from '@/test/render';

import { ChartTooltip } from './components/CumulativePnlCard';
import { toChartData } from './components/chartData';
import { INCOMPLETE_NOTE, recordPnlRanges, openCarteira } from './portfolioPage.support';

// The notifications store is module-global: a notice of one test must not stay for the next.
afterEach(() => {
  notifications.clean();
});

describe('Carteira (§11.4)', () => {
  it('§11.4 OQ-16 starts the cumulative P&L chart 30 days back and ends it on the date', async () => {
    const ranges = recordPnlRanges();
    await openCarteira('2026-10-16');

    await waitFor(() => {
      expect(ranges.at(-1)).toEqual(['2026-09-17', '2026-10-16']);
    });
    expect(screen.getByRole('button', { name: /Início do gráfico/ })).toHaveTextContent(
      '17/09/2026',
    );
  });

  it('§11.4 OQ-16 OQ-48 picking a chart start reloads the chart, and its headline total, up to the date', async () => {
    // The range total on 16/10 depends on where the sum starts.
    server.use(
      http.get(url('/portfolio/pnl'), ({ request }) => {
        const start = new URL(request.url).searchParams.get('start_date');
        const total = start === '2026-10-14' ? '-8034.1345282660' : '1500.0000000000';
        return HttpResponse.json({
          items: pnlSeries.map((p) =>
            p.date === '2026-10-16' ? { ...p, range_cumulative_pnl: total } : p,
          ),
        });
      }),
    );
    // Registered last, so it sees each request first and passes it on.
    const ranges = recordPnlRanges();
    const { user, router } = renderApp('/carteira?date=2026-10-16&pnl_start=2026-10-10');
    await waitFor(() => {
      expect(ranges.at(-1)).toEqual(['2026-10-10', '2026-10-16']);
    });

    const card = within(await screen.findByRole('region', { name: 'P&L acumulado' }));
    expect(await card.findByText('+R$ 1.500,00')).toBeInTheDocument();
    expect(card.getByText('Desde 10/10/2026')).toBeInTheDocument();

    await user.click(await screen.findByRole('button', { name: /Início do gráfico/ }));
    await user.click(await screen.findByRole('button', { name: '14 outubro 2026' }));

    expect(new URLSearchParams(router.state.location.search).get('pnl_start')).toBe('2026-10-14');
    await waitFor(() => {
      expect(ranges.at(-1)).toEqual(['2026-10-14', '2026-10-16']);
    });
    expect(await card.findByText('-R$ 8.034,13')).toBeInTheDocument();
    expect(card.getByText('Desde 14/10/2026')).toBeInTheDocument();
    expect(card.getByText('Até 16/10/2026')).toBeInTheDocument();
  });

  it('§11.4 OQ-16 offers chart starts only before the date', async () => {
    const { user } = renderApp('/carteira?date=2026-10-16&pnl_start=2026-10-10');

    await user.click(await screen.findByRole('button', { name: /Início do gráfico/ }));

    expect(await screen.findByRole('button', { name: '15 outubro 2026' })).toBeEnabled();
    // A disabled day is out of the accessibility tree's buttons; find it by its label.
    expect(screen.getByLabelText('16 outubro 2026')).toBeDisabled();
  });

  it.each(['2026-10-16', '2026-10-20', '2026-13-01', 'abc'])(
    '§11.4 OQ-16 ignores the linked chart start %s, and drops it from the URL',
    async (linked) => {
      const ranges = recordPnlRanges();
      const { router } = renderApp(`/carteira?date=2026-10-16&pnl_start=${linked}`);

      await waitFor(() => {
        expect(ranges.at(-1)).toEqual(['2026-09-17', '2026-10-16']);
      });
      await waitFor(() => {
        expect(router.state.location.search).toBe('?date=2026-10-16');
      });
    },
  );

  it('§11.4 OQ-16 drops a chart start the date has passed, so it never comes back', async () => {
    const ranges = recordPnlRanges();
    const { user, router } = renderApp('/carteira?date=2026-10-16&pnl_start=2026-10-14');
    await waitFor(() => {
      expect(ranges.at(-1)).toEqual(['2026-10-14', '2026-10-16']);
    });

    // A Carteira date before the start drops the start.
    await user.click(await screen.findByRole('button', { name: /Data de avaliação/ }));
    await user.click(await screen.findByRole('button', { name: '10 outubro 2026' }));
    // 10/10 is not processed, so no chart is shown, but the start is still dropped.
    await waitFor(() => {
      expect(router.state.location.search).toBe('?date=2026-10-10');
    });

    // Moving forward again keeps the default, not the old start.
    // The first calendar must have finished closing, or this click would only close it.
    await waitFor(() => {
      expect(document.querySelector('[aria-label="10 outubro 2026"]')).toBeNull();
    });
    await user.click(screen.getByRole('button', { name: /Data de avaliação/ }));
    // jsdom has no layout, so Mantine may hide this calendar as "detached"; find it by label.
    await user.click(await screen.findByLabelText('15 outubro 2026'));
    await waitFor(() => {
      expect(ranges.at(-1)).toEqual(['2026-09-16', '2026-10-15']);
    });
  });

  it('§11.4 OQ-41 says so only when the chosen period is empty', async () => {
    server.use(http.get(url('/portfolio/pnl'), () => HttpResponse.json({ items: [] })));
    await openCarteira('2026-10-15');

    expect(await screen.findByText('Sem dados para o período selecionado.')).toBeInTheDocument();
  });

  it('OQ-41 item 5 notes that incomplete days add zero when the period has any', async () => {
    // The fixture series starts with an unprocessed day.
    await openCarteira('2026-10-15');

    const card = within(screen.getByRole('region', { name: 'P&L acumulado' }));
    expect(await card.findByText(INCOMPLETE_NOTE)).toBeInTheDocument();
    expect(card.queryByText('Sem dados para o período selecionado.')).not.toBeInTheDocument();
  });

  it('OQ-41 item 5 shows no note when every day of the period is complete', async () => {
    // 14/10 to 15/10: both processed with a daily P&L.
    server.use(
      http.get(url('/portfolio/pnl'), () =>
        HttpResponse.json({
          items: pnlSeries.filter((p) => p.date === '2026-10-14' || p.date === '2026-10-15'),
        }),
      ),
    );
    const ranges = recordPnlRanges();
    renderApp('/carteira?date=2026-10-15&pnl_start=2026-10-14');
    const card = within(await screen.findByRole('region', { name: 'P&L acumulado' }));

    await waitFor(() => {
      expect(ranges.at(-1)).toEqual(['2026-10-14', '2026-10-15']);
    });
    expect(await card.findByText('P&L diário somado desde o início escolhido.')).toBeVisible();
    expect(card.queryByText(INCOMPLETE_NOTE)).not.toBeInTheDocument();
  });

  it.each([
    ['NOT_PROCESSED', null, 'Não processado'],
    ['FAILED', null, 'Erro'],
    ['RUNNING', null, 'Processando'],
    ['PROCESSED_WITH_ISSUES', null, 'P&L diário indisponível'],
  ] as const)(
    'OQ-41 item 5 the tooltip of a %s day says why it adds nothing',
    (status, daily, reason) => {
      const [point] = toChartData([
        {
          date: '2026-10-17',
          status,
          daily_pnl: daily,
          range_cumulative_pnl: '-8034.1345282660',
        },
      ]);
      renderUi(<ChartTooltip active payload={[{ payload: point }]} />);

      expect(screen.getByText('17/10/2026')).toBeInTheDocument();
      expect(screen.getByText(reason)).toBeInTheDocument();
    },
  );
});
