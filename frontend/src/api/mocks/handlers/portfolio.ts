import { http, HttpResponse } from 'msw';

import type { ListResponse, PnlPoint, PortfolioPositions, PortfolioSummary } from '../../contract';
import { db, isStale } from '../db';
import { dateErrors, latency, problem, rangeErrors, url } from './support';

// Published results start as the fixtures; a finished job replaces its days with the
// precomputed results of the scenario (handlers/processing.ts). Stale flags follow the live
// dirty markers, so edits show as stale.

function dateParam(request: Request) {
  const date = new URL(request.url).searchParams.get('date');
  return { date, errors: dateErrors(date, 'date') };
}

export const portfolioHandlers = [
  http.get(url('/portfolio/summary'), async ({ request }) => {
    await latency();
    const { date, errors } = dateParam(request);
    if (errors.length > 0 || !date) return problem(422, errors);
    const published = db.published.summaries.get(date);
    const body: PortfolioSummary = published
      ? { ...published, stale: isStale(date) }
      : { date, publication: 'NOT_PROCESSED' };
    return HttpResponse.json(body);
  }),

  http.get(url('/portfolio/positions'), async ({ request }) => {
    await latency();
    const { date, errors } = dateParam(request);
    if (errors.length > 0 || !date) return problem(422, errors);
    const published = db.published.positions.get(date);
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
    const items = [...db.published.pnl.values()]
      .filter((p) => p.date >= (start as string) && p.date <= (end as string))
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((p) => ({ ...p, stale: isStale(p.date) }));
    return HttpResponse.json<ListResponse<PnlPoint>>({ items });
  }),
];

/** Whether the mock has published results for `date`, for the processing preview. */
export const isPublished = (date: string) => db.published.summaries.has(date);

/** The earliest date with any ledger entry (the day before it is the zero state). */
export function firstEntryDate(): string | undefined {
  return [...db.trades.map((t) => t.trade_date), ...db.cashMovements.map((m) => m.movement_date)]
    .sort()
    .at(0);
}
