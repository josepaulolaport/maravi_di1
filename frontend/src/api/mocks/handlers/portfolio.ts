import { http, HttpResponse } from 'msw';

import type { ListResponse, PnlPoint, PortfolioPositions, PortfolioSummary } from '../../contract';
import { db, isStale } from '../db';
import { pnlSeries, positions, summaries } from '../fixtures';
import { dateErrors, latency, problem, rangeErrors, url } from './support';

// Published results are the fixtures; the mock does not recalculate them after a job (only
// the real backend does). Stale flags follow the live dirty markers, so edits show as stale.

function dateParam(request: Request) {
  const date = new URL(request.url).searchParams.get('date');
  return { date, errors: dateErrors(date, 'date') };
}

export const portfolioHandlers = [
  http.get(url('/portfolio/summary'), async ({ request }) => {
    await latency();
    const { date, errors } = dateParam(request);
    if (errors.length > 0 || !date) return problem(422, errors);
    const published = summaries.find((s) => s.date === date);
    const body: PortfolioSummary = published
      ? { ...published, stale: isStale(date) }
      : { date, publication: 'NOT_PROCESSED' };
    return HttpResponse.json(body);
  }),

  http.get(url('/portfolio/positions'), async ({ request }) => {
    await latency();
    const { date, errors } = dateParam(request);
    if (errors.length > 0 || !date) return problem(422, errors);
    const published = positions.find((p) => p.date === date);
    const body: PortfolioPositions = published
      ? { ...published, stale: isStale(date) }
      : { date, publication: 'NOT_PROCESSED' };
    return HttpResponse.json(body);
  }),

  http.get(url('/portfolio/pnl'), async ({ request }) => {
    await latency();
    const params = new URL(request.url).searchParams;
    const start = params.get('start_date');
    const end = params.get('end_date');
    const errors = rangeErrors(start, end);
    if (errors.length > 0) return problem(422, errors);
    const items = pnlSeries
      .filter((p) => p.date >= (start as string) && p.date <= (end as string))
      .map((p) => ({ ...p, stale: isStale(p.date) }));
    return HttpResponse.json<ListResponse<PnlPoint>>({ items });
  }),
];

/** Whether the mock has published results for `date`, for the processing preview. */
export const isPublished = (date: string) => summaries.some((s) => s.date === date);

/** The earliest date with any ledger entry (the day before it is the zero state). */
export function firstEntryDate(): string | undefined {
  return [...db.trades.map((t) => t.trade_date), ...db.cashMovements.map((m) => m.movement_date)]
    .sort()
    .at(0);
}
