import { screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type { PortfolioPositions, PortfolioSummary } from '@/api/contract';
import { positions } from '@/api/mocks/fixtures';
import { summaryOf } from '@/api/mocks/handlers/portfolio';
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

interface SummaryChanges {
  cash?: Partial<PortfolioSummary['cash']>;
  positions?: Partial<PortfolioSummary['positions']>;
  aum?: Partial<PortfolioSummary['aum']>;
}

/**
 * Serves 15/10 (complete and current for both chains in the fixtures) with the given changes
 * to one chain or both, to isolate one state (OQ-21 draft: cash and positions apart).
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
        aum: { ...summary.aum, ...changes.aum },
      };
      return HttpResponse.json(body);
    }),
    http.get(url('/portfolio/positions'), () =>
      HttpResponse.json({ ...rows, status: 'FRESH', ...positionsChanges }),
    ),
  );
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
    expect(screen.queryByText(/desatualizad/)).not.toBeInTheDocument();
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

  it('§10.4 OQ-21 a corrected price makes only positions stale; the link asks for Posições', async () => {
    await openCarteira('2026-10-16');

    expect(screen.getByText('Posições desatualizadas')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ir para Processamentos' })).toHaveAttribute(
      'href',
      '/central-de-controle?tab=processamentos&inicio=2026-10-16&fim=2026-10-16&escopo=posicoes',
    );
    expect(kpi('Saldo em caixa').queryByText('Desatualizado')).not.toBeInTheDocument();
    expect(kpi('P&L operações').getByText('Desatualizado')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('Desatualizado')).toBeInTheDocument();
  });

  it('§11.4 OQ-21 stale cash marks Saldo em caixa and AUM, never the P&L', async () => {
    override15({ cash: { status: 'STALE' }, aum: { status: 'STALE' } });
    await openCarteira('2026-10-15');

    expect(screen.getByText('Caixa desatualizado')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ir para Processamentos' })).toHaveAttribute(
      'href',
      '/central-de-controle?tab=processamentos&inicio=2026-10-15&fim=2026-10-15&escopo=caixa',
    );
    expect(kpi('Saldo em caixa').getByText('Desatualizado')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('Desatualizado')).toBeInTheDocument();
    for (const label of ['P&L diário', 'P&L posições', 'P&L operações']) {
      expect(kpi(label).queryByText('Desatualizado')).not.toBeInTheDocument();
    }
  });

  it('§11.4 OQ-21 both chains stale: one notice that asks for Tudo', async () => {
    override15({
      cash: { status: 'STALE' },
      positions: { status: 'STALE' },
      aum: { status: 'STALE' },
    });
    await openCarteira('2026-10-15');

    expect(screen.getByText('Caixa e posições desatualizados')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ir para Processamentos' })).toHaveAttribute(
      'href',
      '/central-de-controle?tab=processamentos&inicio=2026-10-15&fim=2026-10-15&escopo=tudo',
    );
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
        aum: { status: 'NOT_PROCESSED', value: null },
      },
      { status: 'NOT_PROCESSED', published_at: null, items: [] },
    );
    await openCarteira('2026-10-15');

    expect(screen.getByText('Posições não processadas')).toBeInTheDocument();
    expect(kpi('Saldo em caixa').getByText('R$ 199.650,37')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('—')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('Não processado')).toBeInTheDocument();
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
    override15({ positions: { status: 'STALE' }, aum: { status: 'STALE' } }, { status: 'STALE' });
    await openCarteira('2026-10-15');

    expect(screen.getByText('Posições desatualizadas')).toBeInTheDocument();
    expect(screen.queryByText('Resultados incompletos')).not.toBeInTheDocument();
  });

  it('§8.3 shows only the incomplete notice, and marks the asset, when P&L is missing', async () => {
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

    expect(screen.getByText('Resultados incompletos')).toBeInTheDocument();
    expect(screen.queryByText('Posições desatualizadas')).not.toBeInTheDocument();
    expect(rowOf('DI1F28').getByText('P&L indisponível')).toBeInTheDocument();
    expect(rowOf('DI1F29').queryByText('P&L indisponível')).not.toBeInTheDocument();
  });

  it('§11.4 shows an empty table when no asset is expected on the date', async () => {
    override15({}, { items: [] });
    await openCarteira('2026-10-15');

    expect(screen.getByText('Nenhuma posição nesta data.')).toBeInTheDocument();
  });
});
