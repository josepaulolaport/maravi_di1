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

/** The two data-status badges (user, 2026-10-18): one for the cash, one for the positions. */
function dataStatus() {
  const group = within(screen.getByRole('group', { name: 'Situação dos dados' }));
  return group.getAllByText(/^(Caixa|Posições): /).map((badge) => badge.textContent);
}

/** No KPI carries a status badge of its own; freshness belongs to the chains. */
function expectNoKpiBadge() {
  for (const label of KPIS) {
    expect(kpi(label).queryByText(/Desatualizado|Não processado|Atualizado/)).toBeNull();
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
    expect(dataStatus()).toEqual(['Caixa: Atualizado', 'Posições: Atualizado']);
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

  it('§8.3 an incomplete day shows no card: the figures read "—" and the asset is marked', async () => {
    await openCarteira('2026-10-16');

    expectNoCard();
    expect(kpi('Patrimônio total').getByText('—')).toBeInTheDocument();
    expect(rowOf('DI1F29').getByText('Sem preço')).toBeInTheDocument();
  });

  it('§10.4 OQ-21 a corrected price: only the Posições badge says it', async () => {
    await openCarteira('2026-10-16');

    expectNoCard();
    expect(dataStatus()).toEqual(['Caixa: Atualizado', 'Posições: Desatualizado']);
    expectNoKpiBadge();
  });

  it('§11.4 OQ-21 stale cash shows on the Caixa badge; positions stay current', async () => {
    override15({ cash: { status: 'STALE' }, aum: { status: 'STALE' } });
    await openCarteira('2026-10-15');

    expectNoCard();
    expect(dataStatus()).toEqual(['Caixa: Desatualizado', 'Posições: Atualizado']);
    expectNoKpiBadge();
  });

  it.each([
    ['RUNNING', 'FAILED', ['Caixa: Processando', 'Posições: Erro']],
    ['FRESH', 'FRESH_WITH_ISSUES', ['Caixa: Atualizado', 'Posições: Atualizado com pendências']],
  ] as const)(
    "OQ-23 each badge shows the date's chain status (cash %s, positions %s)",
    async (cash, positions, badges) => {
      override15({ cash: { status: cash }, positions: { status: positions } });
      await openCarteira('2026-10-15');

      expect(dataStatus()).toEqual(badges);
      expectNoKpiBadge();
    },
  );

  it('§11.4 OQ-21 both chains stale: both badges say so, no card', async () => {
    override15({
      cash: { status: 'STALE' },
      positions: { status: 'STALE' },
      aum: { status: 'STALE' },
    });
    await openCarteira('2026-10-15');

    expectNoCard();
    expect(dataStatus()).toEqual(['Caixa: Desatualizado', 'Posições: Desatualizado']);
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

    expectNoCard();
    expect(kpi('Saldo em caixa').getByText('R$ 199.650,37')).toBeInTheDocument();
    expect(kpi('Patrimônio total').getByText('—')).toBeInTheDocument();
    expect(dataStatus()).toEqual(['Caixa: Atualizado', 'Posições: Não processado']);
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
  it('§10.4 a stale but complete day: the Posições badge only', async () => {
    override15({ positions: { status: 'STALE' }, aum: { status: 'STALE' } }, { status: 'STALE' });
    await openCarteira('2026-10-15');

    expectNoCard();
    expect(dataStatus()).toEqual(['Caixa: Atualizado', 'Posições: Desatualizado']);
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
