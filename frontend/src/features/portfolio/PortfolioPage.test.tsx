import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type { PortfolioPositions, PortfolioSummary } from '@/api/contract';
import { positions, summaries } from '@/api/mocks/fixtures';
import { url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { todayInSaoPaulo } from '@/shared/format';
import { renderApp } from '@/test/render';

// Expected figures are the fixture scenario's published values (src/api/mocks/fixtures.ts),
// formatted in pt-BR. Intl puts a no-break space after "R$"; Testing Library's default
// normalizer turns it into a plain space, so expectations use a plain space.

function kpi(label: string) {
  return within(screen.getByRole('group', { name: label }));
}

function rowOf(assetCode: string) {
  const cell = screen.getByText(assetCode, { selector: 'td *' });
  const row = cell.closest('tr');
  if (!row) throw new Error(`no row for ${assetCode}`);
  return within(row);
}

/** Serves 15/10 (complete in the fixtures) with the given changes, to isolate one state. */
function override15(
  summaryChanges: Partial<Extract<PortfolioSummary, { publication: 'PUBLISHED' }>>,
  positionsChanges: Partial<Extract<PortfolioPositions, { publication: 'PUBLISHED' }>> = {},
) {
  const summary = summaries.find((s) => s.date === '2026-10-15');
  const rows = positions.find((p) => p.date === '2026-10-15');
  server.use(
    http.get(url('/portfolio/summary'), () =>
      HttpResponse.json({ ...summary, stale: false, ...summaryChanges }),
    ),
    http.get(url('/portfolio/positions'), () =>
      HttpResponse.json({ ...rows, stale: false, ...positionsChanges }),
    ),
  );
}

/** Records the range of every cumulative P&L request, then lets the mock answer it. */
function recordPnlRanges() {
  const ranges: [string | null, string | null][] = [];
  server.use(
    http.get(url('/portfolio/pnl'), ({ request }) => {
      const params = new URL(request.url).searchParams;
      ranges.push([params.get('start_date'), params.get('end_date')]);
      return undefined;
    }),
  );
  return ranges;
}

async function openCarteira(date: string) {
  const result = renderApp(`/carteira?date=${date}`);
  await screen.findByRole('group', { name: 'Saldo em caixa' });
  return result;
}

describe('Carteira (§11.4)', () => {
  it('§11.4 shows the five KPIs of a complete day, formatted in pt-BR', async () => {
    await openCarteira('2026-10-15');

    expect(kpi('Saldo em caixa').getByText('R$ 199.650,37')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('R$ 1.491.965,87')).toBeInTheDocument();
    expect(kpi('P&L diário').getByText('-R$ 8.034,13')).toBeInTheDocument();
    expect(kpi('P&L posições').getByText('+R$ 1.220,20')).toBeInTheDocument();
    expect(kpi('P&L operações').getByText('-R$ 9.254,33')).toBeInTheDocument();
    expect(screen.queryByText('Resultados desatualizados')).not.toBeInTheDocument();
    expect(screen.queryByText('Resultados incompletos')).not.toBeInTheDocument();
  });

  it('§11.4 shows the cumulative P&L of the same publication', async () => {
    await openCarteira('2026-10-15');

    const card = within(screen.getByRole('region', { name: 'P&L acumulado' }));
    expect(card.getByText('-R$ 8.034,13')).toBeInTheDocument();
    expect(card.getByText('Até 15/10/2026')).toBeInTheDocument();
  });

  it('§11.4 lists the spec columns only: no realized/unrealized P&L and no cash row', async () => {
    await openCarteira('2026-10-15');

    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(headers).toEqual([
      'Ativo',
      'Vencimento',
      'Qtd.',
      'PU médio',
      'Taxa média',
      'PU ref.',
      'Taxa ref.',
      'Valor de mercado',
      'P&L posições',
      'P&L operações',
    ]);
    expect(screen.queryByText(/realizado/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('cell', { name: /^(BRL|Caixa)$/ })).not.toBeInTheDocument();
  });

  it('§11.4 shows each position with its averages, reference and market value', async () => {
    await openCarteira('2026-10-15');

    const row = rowOf('DI1F28');
    for (const text of [
      '03/01/2028',
      '10',
      '89.006,46',
      '10,00%',
      '89.128,48',
      '9,90%',
      'R$ 891.284,82',
      '+R$ 1.220,20',
      'R$ 0,00',
    ]) {
      expect(row.getByText(text)).toBeInTheDocument();
    }
  });

  it('§8.3 keeps cash but shows unavailable figures as "—", never as zero', async () => {
    await openCarteira('2026-10-16');

    expect(kpi('Saldo em caixa').getByText('R$ 506.059,27')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('—')).toBeInTheDocument();
    expect(kpi('P&L diário').getByText('—')).toBeInTheDocument();
    expect(kpi('P&L posições').getByText('—')).toBeInTheDocument();
    expect(kpi('P&L operações').getByText('-R$ 394,71')).toBeInTheDocument();
  });

  it('§8.3 marks the asset without a price and keeps its quantity and average', async () => {
    await openCarteira('2026-10-16');

    const row = rowOf('DI1F29');
    expect(row.getByText('Sem preço')).toBeInTheDocument();
    expect(row.getByText('5')).toBeInTheDocument();
    expect(row.getByText('82.057,00')).toBeInTheDocument();
    // PU ref., Taxa ref., Valor de mercado and P&L posições are unavailable.
    expect(row.getAllByText('—')).toHaveLength(4);
  });

  it('§8.3 flags an incomplete day and links to Pendências', async () => {
    await openCarteira('2026-10-16');

    expect(screen.getByText('Resultados incompletos')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ver pendências' })).toHaveAttribute(
      'href',
      '/central-de-controle?tab=pendencias',
    );
  });

  it('§10.4 flags a stale day and links to Processamentos for that date', async () => {
    await openCarteira('2026-10-16');

    expect(screen.getByText('Resultados desatualizados')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ir para Processamentos' })).toHaveAttribute(
      'href',
      '/central-de-controle?tab=processamentos&inicio=2026-10-16&fim=2026-10-16',
    );
  });

  it('§12 D3 says a date was never processed instead of showing figures', async () => {
    renderApp('/carteira?date=2026-10-17');

    expect(await screen.findByText('Data não processada')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Solicitar processamento' })).toHaveAttribute(
      'href',
      '/central-de-controle?tab=processamentos&inicio=2026-10-17&fim=2026-10-17',
    );
    expect(screen.queryByRole('group', { name: 'Saldo em caixa' })).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('§11.4 shows a loading state, then the data', async () => {
    renderApp('/carteira?date=2026-10-15');

    expect(await screen.findByLabelText('Carregando carteira')).toBeInTheDocument();
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });

  it('§12 shows the API error in pt-BR and retries', async () => {
    server.use(
      http.get(url('/portfolio/summary'), () =>
        HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Erro',
            status: 503,
            detail: 'Serviço indisponível no momento.',
          },
          { status: 503 },
        ),
      ),
    );
    const { user } = renderApp('/carteira?date=2026-10-15');

    expect(await screen.findByText('Serviço indisponível no momento.')).toBeInTheDocument();

    server.resetHandlers();
    await user.click(screen.getByRole('button', { name: 'Tentar novamente' }));
    expect(await screen.findByRole('group', { name: 'Saldo em caixa' })).toBeInTheDocument();
  });

  it('§11.4 filters positions by asset code', async () => {
    const { user } = await openCarteira('2026-10-15');

    await user.type(screen.getByRole('textbox', { name: 'Buscar ativo' }), 'f29');

    expect(screen.getByText('DI1F29', { selector: 'td *' })).toBeInTheDocument();
    expect(screen.queryByText('DI1F28', { selector: 'td *' })).not.toBeInTheDocument();
    await user.clear(screen.getByRole('textbox', { name: 'Buscar ativo' }));
    await user.type(screen.getByRole('textbox', { name: 'Buscar ativo' }), 'DI1F99');
    expect(screen.getByText('Nenhum ativo encontrado.')).toBeInTheDocument();
  });

  it('§11.4 sorts positions by market value, exactly from the decimal strings', async () => {
    const { user } = await openCarteira('2026-10-15');
    const assetOrder = () =>
      screen.getAllByText(/^DI1F\d\d$/, { selector: 'td *' }).map((el) => el.textContent);

    expect(assetOrder()).toEqual(['DI1F28', 'DI1F29']); // by maturity
    await user.click(screen.getByRole('button', { name: 'Valor de mercado' }));
    expect(assetOrder()).toEqual(['DI1F29', 'DI1F28']);
    expect(screen.getByRole('columnheader', { name: 'Valor de mercado' })).toHaveAttribute(
      'aria-sort',
      'ascending',
    );
    await user.click(screen.getByRole('button', { name: 'Valor de mercado' }));
    expect(assetOrder()).toEqual(['DI1F28', 'DI1F29']);
  });

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

  it('§11.4 OQ-16 picking a chart start reloads the chart up to the date and keeps it in the URL', async () => {
    const ranges = recordPnlRanges();
    const { user, router } = renderApp('/carteira?date=2026-10-16&pnl_start=2026-10-10');
    await waitFor(() => {
      expect(ranges.at(-1)).toEqual(['2026-10-10', '2026-10-16']);
    });

    const card = within(await screen.findByRole('region', { name: 'P&L acumulado' }));
    const headline = card.getByText('P&L acumulado').nextElementSibling?.textContent;

    await user.click(await screen.findByRole('button', { name: /Início do gráfico/ }));
    await user.click(await screen.findByRole('button', { name: '14 outubro 2026' }));

    expect(new URLSearchParams(router.state.location.search).get('pnl_start')).toBe('2026-10-14');
    await waitFor(() => {
      expect(ranges.at(-1)).toEqual(['2026-10-14', '2026-10-16']);
    });
    // The headline stays the date's own published figure.
    expect(headline).toBeTruthy();
    expect(card.getByText('P&L acumulado').nextElementSibling).toHaveTextContent(headline ?? '');
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

  it('§11.4 says when the chosen period has no complete history', async () => {
    server.use(http.get(url('/portfolio/pnl'), () => HttpResponse.json({ items: [] })));
    await openCarteira('2026-10-15');

    expect(
      await screen.findByText('Sem histórico completo para exibir no período selecionado.'),
    ).toBeInTheDocument();
  });

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
  });
  it('§10.4 shows only the stale notice for a stale but complete day', async () => {
    override15({ stale: true }, { stale: true });
    await openCarteira('2026-10-15');

    expect(screen.getByText('Resultados desatualizados')).toBeInTheDocument();
    expect(screen.queryByText('Resultados incompletos')).not.toBeInTheDocument();
  });

  it('§8.3 shows only the incomplete notice, and marks the asset, when P&L is missing', async () => {
    const rows = positions.find((p) => p.date === '2026-10-15')?.items ?? [];
    override15(
      { position_pnl: null, daily_pnl: null, cumulative_pnl: null, pnl_status: 'MISSING' },
      {
        items: rows.map((row) =>
          row.asset_code === 'DI1F28'
            ? { ...row, position_pnl: null, daily_pnl: null, pnl_status: 'MISSING' as const }
            : row,
        ),
      },
    );
    await openCarteira('2026-10-15');

    expect(screen.getByText('Resultados incompletos')).toBeInTheDocument();
    expect(screen.queryByText('Resultados desatualizados')).not.toBeInTheDocument();
    expect(rowOf('DI1F28').getByText('P&L indisponível')).toBeInTheDocument();
    expect(rowOf('DI1F29').queryByText('P&L indisponível')).not.toBeInTheDocument();
  });

  it('§11.4 shows an empty table when no asset is expected on the date', async () => {
    override15({}, { items: [] });
    await openCarteira('2026-10-15');

    expect(screen.getByText('Nenhuma posição nesta data.')).toBeInTheDocument();
  });
});
