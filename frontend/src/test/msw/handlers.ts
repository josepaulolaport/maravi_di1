import { http, HttpResponse } from 'msw';

import type {
  LedgerEntry,
  ProcessingRequest,
  ProcessingScope,
  ReferencePrice,
} from '@/api/contract';

import { fieldError, problem, url } from '../helpers';

import * as fixtures from './fixtures';

// The default answer of every endpoint the screens call: the static fixtures, looked up by the
// request's path id or date and nothing more. These handlers keep no state and apply no
// business rule (no search, ordering, pricing, statuses or processing): that is the backend's,
// covered by its own suites, the §13 HTTP scenarios and `make e2e`. A test that needs another
// answer, an error, or what the API returns after a write, says so with `server.use(...)`.

const notFound = (what: string) =>
  problem(404, [fieldError('NOT_FOUND', `${what} não encontrado.`)]);

const param = (request: Request, name: string) => new URL(request.url).searchParams.get(name);

async function body(request: Request): Promise<Record<string, unknown>> {
  return (await request.json()) as Record<string, unknown>;
}

const CREATED_AT = `${fixtures.TEST_TODAY}T12:00:00-03:00`;

export const handlers = [
  http.get(url('/instrument-types'), () => HttpResponse.json({ items: fixtures.instrumentTypes })),
  http.get(url('/products'), () => HttpResponse.json({ items: fixtures.products })),
  http.get(url('/products/:id'), ({ params }) => {
    const product = fixtures.products.find((p) => p.id === params.id);
    return product ? HttpResponse.json(product) : notFound('Produto');
  }),
  http.get(url('/instruments'), () => HttpResponse.json({ items: fixtures.instruments })),
  http.get(url('/instruments/:id'), ({ params }) => {
    const instrument = fixtures.instruments.find((i) => i.id === params.id);
    return instrument ? HttpResponse.json(instrument) : notFound('Contrato');
  }),

  // The entries of the requested dates, newest first.
  http.get(url('/ledger/entries'), ({ request }) => {
    const start = param(request, 'start_date') ?? '';
    const end = param(request, 'end_date') ?? '';
    const items = fixtures.ledgerEntries.filter((e) => e.date >= start && e.date <= end);
    return HttpResponse.json({ items, next_cursor: null });
  }),
  // Echoes the entry with an id. For a trade, the complementary price and `cash_amount` are
  // fixed placeholders, not the backend's figures: a test that shows them serves its own answer.
  http.post(url('/ledger/entries'), async ({ request }) => {
    const entry = await body(request);
    const created = {
      ...entry,
      id: '9a000001-0000-4000-8000-000000000001',
      seq: 6,
      created_at: CREATED_AT,
      ...(entry.type === 'TRADE'
        ? {
            asset_code: fixtures.instruments.find((i) => i.id === entry.asset_id)?.code ?? '',
            instrument_type_code: 'FUTURE',
            execution_pu: entry.execution_pu ?? '89000.0000000000',
            execution_rate: entry.execution_rate ?? '0.100000000000',
            cash_amount: '0',
          }
        : {}),
    } as LedgerEntry;
    return HttpResponse.json(created, { status: 201 });
  }),
  http.post(url('/ledger/entries/deletions'), () => new HttpResponse(null, { status: 204 })),

  // The asset's days with an observation within the requested dates.
  http.get(url('/reference-prices'), ({ request }) => {
    const start = param(request, 'start_date') ?? '';
    const end = param(request, 'end_date') ?? '';
    const days = fixtures.referencePriceDays[param(request, 'asset_id') ?? ''] ?? [];
    const items = days.filter((d) => d.reference_date >= start && d.reference_date <= end);
    return HttpResponse.json({ items });
  }),
  http.post(url('/reference-prices'), async ({ request }) => {
    const price = await body(request);
    const created: ReferencePrice = {
      id: '9a000002-0000-4000-8000-000000000002',
      asset_id: price.asset_id as string,
      reference_date: price.reference_date as string,
      source: 'MANUAL',
      input_kind: price.input_kind as ReferencePrice['input_kind'],
      pu: (price.pu as string | undefined) ?? '89000.0000000000',
      rate: (price.rate as string | undefined) ?? '0.100000000000',
      created_at: CREATED_AT,
    };
    return HttpResponse.json(created, { status: 201 });
  }),
  http.delete(url('/reference-prices/:id'), () => new HttpResponse(null, { status: 204 })),

  http.get(url('/portfolio/summary'), ({ request }) => {
    const date = param(request, 'date') ?? '';
    return HttpResponse.json(fixtures.summaries[date] ?? fixtures.unprocessedSummary(date));
  }),
  http.get(url('/portfolio/positions'), ({ request }) => {
    const date = param(request, 'date') ?? '';
    return HttpResponse.json(fixtures.positions[date] ?? fixtures.unprocessedPositions(date));
  }),
  http.get(url('/portfolio/pnl'), () => HttpResponse.json({ items: fixtures.pnlSeries })),

  http.get(url('/processing/requests'), () =>
    HttpResponse.json({ items: fixtures.processingRequests, next_cursor: null }),
  ),
  http.get(url('/processing/preview'), () => HttpResponse.json(fixtures.preview)),
  // The new run, queued.
  http.post(url('/processing/requests'), async ({ request }) => {
    const requested = await body(request);
    const created: ProcessingRequest = fixtures.job({
      id: '9a000003-0000-4000-8000-000000000003',
      start_date: requested.start_date as string,
      end_date: requested.end_date as string,
      scope: requested.scope as ProcessingScope,
      created_at: CREATED_AT,
      updated_at: CREATED_AT,
    });
    return HttpResponse.json(created, { status: 201 });
  }),
  // A queued run, cancelled at once.
  http.post(url('/processing/requests/:id/cancel'), ({ params }) =>
    HttpResponse.json(
      fixtures.job({
        id: params.id as string,
        status: 'CANCELLED',
        cancel_requested_at: CREATED_AT,
        finished_at: CREATED_AT,
      }),
    ),
  ),
  http.get(url('/processing/issues'), () => HttpResponse.json({ items: fixtures.issues })),
];
