import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import type { PortfolioPositions, PortfolioSummary } from '@/api/contract';
import { positions } from '@/api/mocks/fixtures';
import { summaryOf } from '@/api/mocks/handlers/portfolio';
import { url } from '@/api/mocks/handlers/support';
import { server } from '@/api/mocks/server';
import { todayInSaoPaulo } from '@/shared/format';
import { renderApp, renderUi } from '@/test/render';

import { ChartTooltip } from './components/CumulativePnlCard';
import { toChartData } from './components/chartData';

const INCOMPLETE_NOTE =
  'Há dias incompletos no período (não processados, com erro, em processamento ou sem P&L diário): eles somam zero ao acumulado.';

// Expected figures are the fixture scenario's published values (src/api/mocks/fixtures.ts),
// formatted in pt-BR. Intl puts a no-break space after "R$"; Testing Library's default
// normalizer turns it into a plain space, so expectations use a plain space.

// The notifications store is module-global: a notice of one test must not stay for the next.
afterEach(() => {
  notifications.clean();
});

function kpi(label: string) {
  return within(screen.getByRole('group', { name: label }));
}

/** The two data-status badges (user, 2026-10-18): one for the cash, one for the positions. */
function dataStatus() {
  const group = within(screen.getByRole('group', { name: 'Situação dos dados' }));
  return group.getAllByText(/^(Caixa|Posições): /).map((badge) => badge.textContent);
}

/** No KPI carries a status badge of its own; the status belongs to the chains. */
function expectNoKpiBadge() {
  for (const label of KPIS) {
    expect(
      kpi(label).queryByText(
        /^(Processado|Processado com pendências|Processando|Erro|Não processado)$/,
      ),
    ).toBeNull();
  }
}

/** No notice card above the figures (user, 2026-10-18): the two badges tell the state. */
function expectNoCard() {
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
}

const KPIS = ['Saldo em caixa', 'Patrimônio total', 'P&L diário', 'P&L posições', 'P&L operações'];

function rowOf(assetCode: string) {
  const cell = screen.getByText(assetCode, { selector: 'td *' });
  const row = cell.closest('tr');
  if (!row) throw new Error(`no row for ${assetCode}`);
  return within(row);
}

interface SummaryChanges {
  cash?: Partial<PortfolioSummary['cash']>;
  positions?: Partial<PortfolioSummary['positions']>;
  aum?: PortfolioSummary['aum'];
}

/**
 * Serves 15/10 (complete and current for both chains in the fixtures) with the given changes
 * to one chain or both, to isolate one state (OQ-21: cash and positions apart).
 */
function override15(changes: SummaryChanges, positionsChanges: Partial<PortfolioPositions> = {}) {
  const rows = positions.find((p) => p.date === '2026-10-15');
  server.use(
    http.get(url('/portfolio/summary'), () => {
      const summary = summaryOf('2026-10-15');
      const body: PortfolioSummary = {
        ...summary,
        cash: { ...summary.cash, ...changes.cash },
        positions: { ...summary.positions, ...changes.positions },
        aum: changes.aum === undefined ? summary.aum : changes.aum,
      };
      return HttpResponse.json(body);
    }),
    http.get(url('/portfolio/positions'), () =>
      HttpResponse.json({ ...rows, status: 'PROCESSED', ...positionsChanges }),
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
  it('§11 names the page and the browser tab', async () => {
    await openCarteira('2026-10-15');

    expect(screen.getByRole('heading', { level: 1, name: 'Carteira' })).toBeInTheDocument();
    expect(document.title).toBe('Carteira · Maravi Backoffice');
  });

  it('§11.4 shows the five KPIs of a complete day, formatted in pt-BR', async () => {
    await openCarteira('2026-10-15');

    expect(kpi('Saldo em caixa').getByText('R$ 199.650,37')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('R$ 1.491.965,87')).toBeInTheDocument();
    expect(kpi('P&L diário').getByText('-R$ 8.034,13')).toBeInTheDocument();
    expect(kpi('P&L posições').getByText('+R$ 1.220,20')).toBeInTheDocument();
    expect(kpi('P&L operações').getByText('-R$ 9.254,33')).toBeInTheDocument();
    expect(dataStatus()).toEqual(['Caixa: Processado', 'Posições: Processado']);
    expectNoKpiBadge();
    expectNoCard();
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
      '10,0000%',
      '89.128,48',
      '9,9000%',
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

  it('§8.3 an incomplete day shows no card: the figures read "—" and the asset is marked', async () => {
    await openCarteira('2026-10-16');

    expectNoCard();
    expect(kpi('Patrimônio total').getByText('—')).toBeInTheDocument();
    expect(rowOf('DI1F29').getByText('Sem preço')).toBeInTheDocument();
  });

  it('OQ-31 a price corrected after processing changes no badge', async () => {
    await openCarteira('2026-10-16');

    expectNoCard();
    expect(dataStatus()).toEqual(['Caixa: Processado', 'Posições: Processado com pendências']);
    expectNoKpiBadge();
  });

  it('OQ-31 each badge shows when its chain was processed, in Brasília time', async () => {
    override15({ cash: { published_at: '2026-10-18T12:05:00-03:00' } });
    await openCarteira('2026-10-15');

    const status = within(screen.getByRole('group', { name: 'Situação dos dados' }));
    expect(status.getAllByText(/^Processado em /).map((time) => time.textContent)).toEqual([
      'Processado em 18/10/2026 12:05',
      'Processado em 16/10/2026 18:40',
    ]);
  });

  it('OQ-30 a position shows the current reference price, even one corrected after processing', async () => {
    await openCarteira('2026-10-16');

    const row = rowOf('DI1F28');
    expect(row.getByText('89.250,31')).toBeInTheDocument();
    expect(row.getByText('9,8000%')).toBeInTheDocument();
    // The market value is the processed one (89.200,90 × 6).
    expect(row.getByText('R$ 535.205,41')).toBeInTheDocument();
  });

  it.each([
    ['RUNNING', 'FAILED', ['Caixa: Processando', 'Posições: Erro']],
    [
      'PROCESSED',
      'PROCESSED_WITH_ISSUES',
      ['Caixa: Processado', 'Posições: Processado com pendências'],
    ],
  ] as const)(
    "OQ-23 each badge shows the date's chain status (cash %s, positions %s)",
    async (cash, positions, badges) => {
      override15({ cash: { status: cash }, positions: { status: positions } });
      await openCarteira('2026-10-15');

      expect(dataStatus()).toEqual(badges);
      expectNoKpiBadge();
    },
  );

  it('OQ-23 a date being processed is read again until it is done, without a reload', async () => {
    let reads = 0;
    server.use(
      http.get(url('/portfolio/summary'), () => {
        reads += 1;
        const summary = summaryOf('2026-10-15');
        const running = { ...summary.positions, status: 'RUNNING' as const };
        return HttpResponse.json<PortfolioSummary>(
          reads === 1 ? { ...summary, positions: running } : summary,
        );
      }),
    );
    await openCarteira('2026-10-15');
    expect(dataStatus()).toEqual(['Caixa: Processado', 'Posições: Processando']);

    // Polled every 2 s while a chain is RUNNING (§12); the wait allows one poll under load.
    await waitFor(
      () => {
        expect(dataStatus()).toEqual(['Caixa: Processado', 'Posições: Processado']);
      },
      { timeout: 5_000 },
    );
    expect(reads).toBeGreaterThanOrEqual(2);
  });

  it('OQ-23 when a date finishes processing, its positions are read again too', async () => {
    let summaryReads = 0;
    let positionsReads = 0;
    const rows = positions.find((p) => p.date === '2026-10-15');
    server.use(
      http.get(url('/portfolio/summary'), () => {
        summaryReads += 1;
        const summary = summaryOf('2026-10-15');
        const running = { ...summary.positions, status: 'RUNNING' as const };
        return HttpResponse.json<PortfolioSummary>(
          summaryReads === 1 ? { ...summary, positions: running } : summary,
        );
      }),
      // Before the run commits, the date had no positions published.
      http.get(url('/portfolio/positions'), () => {
        positionsReads += 1;
        const body: PortfolioPositions =
          positionsReads === 1
            ? { date: '2026-10-15', status: 'RUNNING', published_at: null, items: [] }
            : {
                date: '2026-10-15',
                status: 'PROCESSED',
                published_at: null,
                items: rows?.items ?? [],
              };
        return HttpResponse.json(body);
      }),
    );
    await openCarteira('2026-10-15');

    expect(
      await screen.findByText('DI1F28', { selector: 'td *' }, { timeout: 5_000 }),
    ).toBeInTheDocument();
    expect(positionsReads).toBeGreaterThanOrEqual(2);
  });

  it('OQ-23 moving from a date being processed to another date reads the new date once', async () => {
    const summaryReads: string[] = [];
    server.use(
      http.get(url('/portfolio/summary'), ({ request }) => {
        const date = new URL(request.url).searchParams.get('date') ?? '';
        summaryReads.push(date);
        const summary = summaryOf(date);
        return HttpResponse.json<PortfolioSummary>(
          date === '2026-10-15'
            ? { ...summary, positions: { ...summary.positions, status: 'RUNNING' } }
            : summary,
        );
      }),
    );
    const { router } = await openCarteira('2026-10-15');
    expect(dataStatus()).toEqual(['Caixa: Processado', 'Posições: Processando']);

    await router.navigate('/carteira?date=2026-10-16');

    await waitFor(() => {
      expect(screen.getByText('DI1F29', { selector: 'td *' })).toBeInTheDocument();
    });
    // Leaving a RUNNING date is not "the date finished processing": nothing is re-read.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(summaryReads.filter((date) => date === '2026-10-16')).toHaveLength(1);
  });

  it("§11.4 a failed chain's badge leads to Processamentos for that date and chain", async () => {
    override15({ positions: { status: 'FAILED' } });
    await openCarteira('2026-10-15');

    const status = within(screen.getByRole('group', { name: 'Situação dos dados' }));
    expect(
      status.getByRole('link', { name: 'Posições: Erro. Ir para Processamentos' }),
    ).toHaveAttribute(
      'href',
      '/central-de-controle?tab=processamentos&inicio=2026-10-15&fim=2026-10-15&escopo=posicoes',
    );
    // A current chain needs nothing: its badge is no link.
    expect(status.queryByRole('link', { name: /^Caixa/ })).not.toBeInTheDocument();
  });

  it('OQ-21 shows what moved the cash on the date under Saldo em caixa', async () => {
    await openCarteira('2026-10-16');

    const movement = within(
      kpi('Saldo em caixa').getByRole('group', { name: 'Movimentação do caixa no dia' }),
    );
    expect(movement.getByText('Operações').nextSibling).toHaveTextContent('+R$ 356.408,89');
    expect(movement.getByText('Aportes').nextSibling).toHaveTextContent('R$ 0,00');
    expect(movement.getByText('Retiradas').nextSibling).toHaveTextContent('R$ 50.000,00');
  });

  it('§11.4 never breaks a KPI figure, so a minus sign cannot wrap alone (QA 2026-10-19 #2)', async () => {
    await openCarteira('2026-10-16');

    const figures = KPIS.flatMap((label) => kpi(label).queryAllByText(/R\$/));
    // At least Saldo em caixa and its three movement lines.
    expect(figures.length).toBeGreaterThanOrEqual(4);
    for (const figure of figures) {
      expect(figure).toHaveStyle({ whiteSpace: 'nowrap' });
    }
  });

  it('§11.4 a badge with issues leads to Pendências', async () => {
    override15({ positions: { status: 'PROCESSED_WITH_ISSUES' } });
    await openCarteira('2026-10-15');

    expect(
      screen.getByRole('link', { name: 'Posições: Processado com pendências. Ver pendências' }),
    ).toHaveAttribute('href', '/central-de-controle?tab=pendencias');
  });

  it('§11.4 OQ-21 both chains failed: both badges say so, no card', async () => {
    override15({
      cash: { status: 'FAILED' },
      positions: { status: 'FAILED' },
    });
    await openCarteira('2026-10-15');

    expectNoCard();
    expect(dataStatus()).toEqual(['Caixa: Erro', 'Posições: Erro']);
  });

  it('§11.4 OQ-21 cash processed but positions not: cash shows, AUM and positions do not', async () => {
    override15(
      {
        positions: {
          status: 'NOT_PROCESSED',
          published_at: null,
          market_value: null,
          valuation_status: null,
          position_pnl: null,
          trades_pnl: null,
          daily_pnl: null,
          cumulative_pnl: null,
          pnl_status: null,
        },
        aum: null,
      },
      { status: 'NOT_PROCESSED', published_at: null, items: [] },
    );
    await openCarteira('2026-10-15');

    expectNoCard();
    expect(kpi('Saldo em caixa').getByText('R$ 199.650,37')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('—')).toBeInTheDocument();
    expect(dataStatus()).toEqual(['Caixa: Processado', 'Posições: Não processado']);
    expectNoKpiBadge();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('§12 D3 says a date was never processed instead of showing figures', async () => {
    renderApp('/carteira?date=2026-10-17');

    expect(await screen.findByText('Data não processada')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Solicitar processamento' })).toHaveAttribute(
      'href',
      '/central-de-controle?tab=processamentos&inicio=2026-10-17&fim=2026-10-17&escopo=tudo',
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

  it('§11.4 filters positions by asset code, with the search in the URL', async () => {
    const { user, router } = await openCarteira('2026-10-15');

    await user.type(screen.getByRole('textbox', { name: 'Buscar ativo' }), 'f29');

    await waitFor(() => {
      expect(screen.queryByText('DI1F28', { selector: 'td *' })).not.toBeInTheDocument();
    });
    expect(screen.getByText('DI1F29', { selector: 'td *' })).toBeInTheDocument();
    expect(router.state.location.search).toContain('busca=f29');
    await user.clear(screen.getByRole('textbox', { name: 'Buscar ativo' }));
    await user.type(screen.getByRole('textbox', { name: 'Buscar ativo' }), 'DI1F99');
    expect(await screen.findByText('Nenhum ativo encontrado.')).toBeInTheDocument();
  });

  it('§11.4 reads the positions search and order from the URL (a linked view)', async () => {
    renderApp('/carteira?date=2026-10-15&busca=f2&ordem=-financial_total');
    await screen.findByRole('group', { name: 'Saldo em caixa' });

    expect(screen.getByRole('textbox', { name: 'Buscar ativo' })).toHaveValue('f2');
    expect(screen.getByRole('columnheader', { name: 'Valor de mercado' })).toHaveAttribute(
      'aria-sort',
      'descending',
    );
    expect(
      screen.getAllByText(/^DI1F\d\d$/, { selector: 'td *' }).map((el) => el.textContent),
    ).toEqual(['DI1F28', 'DI1F29']);
  });

  it('§11.4 sorts positions by market value, exactly from the decimal strings', async () => {
    const { user, router } = await openCarteira('2026-10-15');
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
    expect(router.state.location.search).toContain('ordem=-financial_total');
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

  it('§11.4 OQ-41 says so only when the chosen period is empty', async () => {
    server.use(http.get(url('/portfolio/pnl'), () => HttpResponse.json({ items: [] })));
    await openCarteira('2026-10-15');

    expect(await screen.findByText('Sem dados para o período selecionado.')).toBeInTheDocument();
  });

  it('OQ-41 item 5 notes that incomplete days add zero when the period has any', async () => {
    // The default 30 days before 15/10 are mostly not processed.
    await openCarteira('2026-10-15');

    const card = within(screen.getByRole('region', { name: 'P&L acumulado' }));
    expect(await card.findByText(INCOMPLETE_NOTE)).toBeInTheDocument();
    expect(card.queryByText('Sem dados para o período selecionado.')).not.toBeInTheDocument();
  });

  it('OQ-41 item 5 shows no note when every day of the period is complete', async () => {
    // 14/10 to 15/10: both processed with a daily P&L.
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
          cumulative_pnl: null,
          pnl_status: null,
          range_cumulative_pnl: '-8034.1345282660',
          published_at: null,
        },
      ]);
      renderUi(<ChartTooltip active payload={[{ payload: point }]} />);

      expect(screen.getByText('17/10/2026')).toBeInTheDocument();
      expect(screen.getByText(reason)).toBeInTheDocument();
    },
  );

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

  it('§8.3 P&L missing: no card, the asset is marked', async () => {
    const rows = positions.find((p) => p.date === '2026-10-15')?.items ?? [];
    override15(
      {
        positions: {
          position_pnl: null,
          daily_pnl: null,
          cumulative_pnl: null,
          pnl_status: 'MISSING',
        },
      },
      {
        items: rows.map((row) =>
          row.asset_code === 'DI1F28'
            ? { ...row, position_pnl: null, daily_pnl: null, pnl_status: 'MISSING' as const }
            : row,
        ),
      },
    );
    await openCarteira('2026-10-15');

    expectNoCard();
    expect(rowOf('DI1F28').getByText('P&L indisponível')).toBeInTheDocument();
    expect(rowOf('DI1F29').queryByText('P&L indisponível')).not.toBeInTheDocument();
  });

  it('§11.4 shows an empty table when no asset is expected on the date', async () => {
    override15({}, { items: [] });
    await openCarteira('2026-10-15');

    expect(screen.getByText('Nenhuma posição nesta data.')).toBeInTheDocument();
  });
});
