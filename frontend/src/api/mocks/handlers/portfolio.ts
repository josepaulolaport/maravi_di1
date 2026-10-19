import { http, HttpResponse } from 'msw';

import type { ListResponse, PnlPoint, PortfolioPositions, PortfolioSummary } from '../../contract';
import { db, statusOf } from '../db';
import { dateErrors, latency, problem, rangeErrors, url } from './support';

// Published results start as the fixtures; a finished job replaces the days of its scope with
// the precomputed results of the scenario (handlers/processing.ts). Cash and positions are
// served apart, each with its date status (OQ-21, OQ-23); AUM joins them.

function dateParam(request: Request) {
  const date = new URL(request.url).searchParams.get('date');
  return { date, errors: dateErrors(date, 'date') };
}

export function summaryOf(date: string): PortfolioSummary {
  const cash = db.published.cash.get(date);
  const positions = db.published.summaries.get(date);
  const cashStatus = statusOf(date, 'CASH');
  const positionsStatus = statusOf(date, 'POSITIONS');
  return {
    date,
    cash: {
      status: cashStatus,
      balance: cash?.balance ?? null,
      trades_cash_flow: cash?.trades_cash_flow ?? null,
      deposits: cash?.deposits ?? null,
      withdrawals: cash?.withdrawals ?? null,
      published_at: cash?.published_at ?? null,
    },
    positions: {
      status: positionsStatus,
      published_at: positions?.published_at ?? null,
      market_value: positions?.positions_market_value ?? null,
      valuation_status: positions?.valuation_status ?? null,
      position_pnl: positions?.position_pnl ?? null,
      trades_pnl: positions?.trades_pnl ?? null,
      daily_pnl: positions?.daily_pnl ?? null,
      cumulative_pnl: positions?.cumulative_pnl ?? null,
      pnl_status: positions?.pnl_status ?? null,
    },
    // The scenario's cash + market value, only while both sides are published.
    aum: cash && positions ? positions.aum : null,
  };
}

export const portfolioHandlers = [
  http.get(url('/portfolio/summary'), async ({ request }) => {
    await latency();
    const { date, errors } = dateParam(request);
    if (errors.length > 0 || !date) return problem(422, errors);
    return HttpResponse.json<PortfolioSummary>(summaryOf(date));
  }),

  http.get(url('/portfolio/positions'), async ({ request }) => {
    await latency();
    const { date, errors } = dateParam(request);
    if (errors.length > 0 || !date) return problem(422, errors);
    const published = db.published.positions.get(date);
    const body: PortfolioPositions = {
      date,
      status: statusOf(date, 'POSITIONS'),
      published_at: published?.published_at ?? null,
      items: published?.items ?? [],
    };
    return HttpResponse.json(body);
  }),

  http.get(url('/portfolio/pnl'), async ({ request }) => {
    await latency();
    const params = new URL(request.url).searchParams;
    const start = params.get('start_date');
    const end = params.get('end_date');
    const errors = rangeErrors(start, end);
    if (errors.length > 0) return problem(422, errors);
    const items = [...db.published.pnl.values()]
      .filter((p) => p.date >= (start as string) && p.date <= (end as string))
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((p) => ({ ...p, status: statusOf(p.date, 'POSITIONS') }));
    return HttpResponse.json<ListResponse<PnlPoint>>({ items });
  }),
];
