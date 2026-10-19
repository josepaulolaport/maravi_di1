import { http, HttpResponse } from 'msw';

import type { ListResponse, PnlPoint, PortfolioPositions, PortfolioSummary } from '../../contract';
import { addDays } from '../dates';
import { db, statusOf } from '../db';
import { addDecimal } from '../decimal';
import { preferredOf } from './prices';
import { dateErrors, latency, problem, rangeErrors, url } from './support';

// Published results start as the fixtures; a finished job replaces the days of its scope with
// the precomputed results of the scenario (handlers/processing.ts). Cash and positions are
// served apart, each with its date status and processing time (OQ-21, OQ-23, OQ-31); AUM
// joins them.

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
    // As the last chain written on the date stored it (OQ-38, OQ-40), while both sides exist.
    aum: cash && positions ? (db.published.aum.get(date) ?? null) : null,
  };
}

/**
 * A position row's reference price is the date's current preferred price, read from the price
 * table (OQ-30): MANUAL, else B3, exact date; after maturity the PU is 0.
 */
function referenceOf(
  row: PortfolioPositions['items'][number],
  date: string,
): Pick<
  PortfolioPositions['items'][number],
  'reference_pu' | 'reference_rate' | 'reference_source'
> {
  if (row.maturity_date !== null && date > row.maturity_date) {
    return { reference_pu: '0', reference_rate: null, reference_source: null };
  }
  const price = preferredOf(row.asset_id, date);
  return price
    ? { reference_pu: price.pu, reference_rate: price.rate, reference_source: price.source }
    : { reference_pu: null, reference_rate: null, reference_source: null };
}

/**
 * The P&L series over [start, end] (OQ-16, OQ-31 item 8, OQ-41): one point per calendar date,
 * with the positions status and processing time, and `range_cumulative_pnl`, the daily P&L
 * summed from `start` (its own included). Only a PROCESSED or PROCESSED_WITH_ISSUES day shows
 * its P&L and adds a non-null daily P&L; every other day shows none and adds 0 (item 4), even
 * over an older published row, so the sum is never null and the line never breaks.
 */
function pnlSeries(start: string, end: string): PnlPoint[] {
  const items: PnlPoint[] = [];
  let sum = '0';
  for (let date = start; date <= end; date = addDays(date, 1)) {
    const status = statusOf(date, 'POSITIONS');
    const processed = status === 'PROCESSED' || status === 'PROCESSED_WITH_ISSUES';
    const point = processed ? db.published.pnl.get(date) : undefined;
    if (point?.daily_pnl != null) sum = addDecimal(sum, point.daily_pnl);
    items.push({
      date,
      status,
      // A FAILED or RUNNING day keeps its stored processing time; a day never processed has none.
      published_at:
        status === 'NOT_PROCESSED'
          ? null
          : (db.published.summaries.get(date)?.published_at ?? null),
      pnl_status: point?.pnl_status ?? null,
      daily_pnl: point?.daily_pnl ?? null,
      cumulative_pnl: point?.cumulative_pnl ?? null,
      range_cumulative_pnl: sum,
    });
  }
  return items;
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
      items: (published?.items ?? []).map((row) => ({ ...row, ...referenceOf(row, date) })),
    };
    return HttpResponse.json(body);
  }),

  http.get(url('/portfolio/pnl'), async ({ request }) => {
    await latency();
    const params = new URL(request.url).searchParams;
    const start = params.get('start_date');
    const end = params.get('end_date');
    // A series ending after today is FUTURE_DATE on end_date (OQ-35 item 2).
    const errors = rangeErrors(start, end, { future: 'end' });
    if (errors.length > 0) return problem(422, errors);
    return HttpResponse.json<ListResponse<PnlPoint>>({
      items: pnlSeries(start as string, end as string),
    });
  }),
];
