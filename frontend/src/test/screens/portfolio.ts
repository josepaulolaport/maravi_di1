import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type { PortfolioPositions, PortfolioSummary } from '@/api/contract';
import { positions, summaries, unprocessedSummary } from '@/test/msw/fixtures';
import { url } from '@/test/helpers';
import { server } from '@/test/msw/server';
import { renderRoute } from '@/test/render';

export const INCOMPLETE_NOTE =
  'Há dias incompletos no período (não processados, com erro, em processamento ou sem P&L diário): eles somam zero ao acumulado.';

// Expected figures are the fixtures' published values (src/test/msw/fixtures.ts),
// formatted in pt-BR. Intl puts a no-break space after "R$"; Testing Library's default
// normalizer turns it into a plain space, so expectations use a plain space.

export function kpi(label: string) {
  return within(screen.getByRole('group', { name: label }));
}

/** The two data-status badges (user, 2026-10-18): one for the cash, one for the positions. */
export function dataStatus() {
  const group = within(screen.getByRole('group', { name: 'Situação dos dados' }));
  return group.getAllByText(/^(Caixa|Posições): /).map((badge) => badge.textContent);
}

/** No KPI carries a status badge of its own; the status belongs to the chains. */
export function expectNoKpiBadge() {
  for (const label of KPIS) {
    expect(
      kpi(label).queryByText(
        /^(Processado|Processado com pendências|Processando|Erro|Não processado)$/,
      ),
    ).toBeNull();
  }
}

/** No notice card above the figures (user, 2026-10-18): the two badges tell the state. */
export function expectNoCard() {
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
}

export const KPIS = [
  'Saldo em caixa',
  'Patrimônio total',
  'P&L diário',
  'P&L posições',
  'P&L operações',
];

interface SummaryChanges {
  cash?: Partial<PortfolioSummary['cash']>;
  positions?: Partial<PortfolioSummary['positions']>;
  aum?: PortfolioSummary['aum'];
}

/** The fixtures' answer for a date. */
export const summaryOf = (date: string): PortfolioSummary =>
  summaries[date] ?? unprocessedSummary(date);
export const POSITIONS_15 = positions['2026-10-15'] as PortfolioPositions;

/**
 * Serves 15/10 (complete and current for both chains in the fixtures) with the given changes
 * to one chain or both, to isolate one state (OQ-21: cash and positions apart).
 */
export function override15(
  changes: SummaryChanges,
  positionsChanges: Partial<PortfolioPositions> = {},
) {
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
      HttpResponse.json({ ...POSITIONS_15, ...positionsChanges }),
    ),
  );
}

/** Records the range of every cumulative P&L request, then lets the next handler answer it. */
export function recordPnlRanges() {
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

export async function openCarteira(date: string) {
  const result = renderRoute(`/carteira?date=${date}`);
  await screen.findByRole('group', { name: 'Saldo em caixa' });
  return result;
}
