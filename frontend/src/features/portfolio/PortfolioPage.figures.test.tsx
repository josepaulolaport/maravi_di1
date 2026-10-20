import { screen, waitFor, within } from '@testing-library/react';
import { notifications } from '@mantine/notifications';
import { http, HttpResponse } from 'msw';

import type { PortfolioPositions, PortfolioSummary } from '@/api/contract';
import { job } from '@/test/msw/fixtures';
import { url, rowContaining } from '@/test/helpers';
import { server, serveJobs } from '@/test/msw/server';
import { renderRoute } from '@/test/render';

import {
  kpi,
  dataStatus,
  expectNoKpiBadge,
  expectNoCard,
  KPIS,
  summaryOf,
  POSITIONS_15,
  override15,
  openCarteira,
} from '@/test/screens/portfolio';

// The notifications store is module-global: a notice of one test must not stay for the next.
afterEach(() => {
  notifications.clean();
});

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

  it("§11.4 OQ-41 OQ-48 the card's headline is the chart's range total on the date, since its start", async () => {
    // 16/10 has a missing price: its stored cumulative P&L is null, but the range total is not.
    await openCarteira('2026-10-16');

    const card = within(screen.getByRole('region', { name: 'P&L acumulado' }));
    expect(await card.findByText('-R$ 8.034,13')).toBeInTheDocument();
    expect(card.getByText('Desde 17/09/2026')).toBeInTheDocument();
    expect(card.getByText('Até 16/10/2026')).toBeInTheDocument();
  });

  it('§11.4 OQ-48 the headline shows loading, not "—", while the series is read', async () => {
    // The series never answers in this test.
    server.use(http.get(url('/portfolio/pnl'), () => new Promise<Response>(() => undefined)));
    await openCarteira('2026-10-16');

    const card = within(screen.getByRole('region', { name: 'P&L acumulado' }));
    const headline = card.getByText('P&L acumulado').nextElementSibling;
    expect(headline).toHaveAttribute('aria-busy', 'true');
    expect(headline).not.toHaveTextContent('—');
  });

  it('§11.4 OQ-48 the headline reads "—" when the series has no point for the date', async () => {
    server.use(http.get(url('/portfolio/pnl'), () => HttpResponse.json({ items: [] })));
    await openCarteira('2026-10-16');

    const card = within(screen.getByRole('region', { name: 'P&L acumulado' }));
    await card.findByText('Sem dados para o período selecionado.');
    expect(card.getByText('P&L acumulado').nextElementSibling).toHaveTextContent('—');
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

    const row = rowContaining('DI1F28');
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

    const row = rowContaining('DI1F29');
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
    expect(rowContaining('DI1F29').getByText('Sem preço')).toBeInTheDocument();
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

    const row = rowContaining('DI1F28');
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

  it('OQ-23 §10.4 when the run of a date ends, its positions are read again too', async () => {
    const run = { start_date: '2026-10-15', end_date: '2026-10-15', started_at: null };
    const jobs = serveJobs([job({ ...run, status: 'RUNNING' })]);
    let summaryReads = 0;
    let positionsReads = 0;
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
                items: POSITIONS_15.items,
              };
        return HttpResponse.json(body);
      }),
    );
    await openCarteira('2026-10-15');
    // The next poll of the jobs sees the run finished: the JobWatcher refreshes the portfolio.
    jobs.items = [job({ ...run, status: 'COMPLETED', progress_date: '2026-10-15' })];

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
    // Only the JobWatcher refreshes the portfolio, when a run ends: nothing is re-read here.
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
    renderRoute('/carteira?date=2026-10-17');

    expect(await screen.findByText('Data não processada')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Solicitar processamento' })).toHaveAttribute(
      'href',
      '/central-de-controle?tab=processamentos&inicio=2026-10-17&fim=2026-10-17&escopo=tudo',
    );
    expect(screen.queryByRole('group', { name: 'Saldo em caixa' })).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('§11.4 shows a loading state, then the data', async () => {
    renderRoute('/carteira?date=2026-10-15');

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
    const { user } = renderRoute('/carteira?date=2026-10-15');

    expect(await screen.findByText('Serviço indisponível no momento.')).toBeInTheDocument();

    server.resetHandlers();
    await user.click(screen.getByRole('button', { name: 'Tentar novamente' }));
    expect(await screen.findByRole('group', { name: 'Saldo em caixa' })).toBeInTheDocument();
  });
});
