import { http, HttpResponse } from 'msw';

import type {
  InputKind,
  FieldError,
  ListResponse,
  ReferencePrice,
  ReferencePriceDay,
} from '../../contract';
import { daysInclusive } from '../dates';
import { db, markDirty, newId } from '../db';
import {
  dateErrors,
  decimalErrors,
  fakePricing,
  fieldError,
  findInstrument,
  latency,
  notFound,
  problem,
  rangeErrors,
  readJson,
  url,
} from './support';

const current = (assetId: string, date: string) =>
  db.referencePrices.filter(
    (p) => p.asset_id === assetId && p.reference_date === date && p.superseded_at === null,
  );

/** MANUAL wins over B3 for the same asset and date (§5). */
export function preferredOf(assetId: string, date: string): ReferencePrice | undefined {
  const observations = current(assetId, date);
  return (
    observations.find((p) => p.source === 'MANUAL') ?? observations.find((p) => p.source === 'B3')
  );
}

export const priceHandlers = [
  http.get(url('/reference-prices'), async ({ request }) => {
    await latency();
    const params = new URL(request.url).searchParams;
    const assetId = params.get('asset_id') ?? '';
    const start = params.get('start_date');
    const end = params.get('end_date');
    const errors = rangeErrors(start, end);
    if (!findInstrument(assetId)) {
      errors.push(fieldError('VALIDATION_ERROR', 'Selecione um contrato.', 'asset_id'));
    }
    if (errors.length > 0) return problem(422, errors);

    const dates = [
      ...new Set(
        db.referencePrices
          .filter((p) => p.asset_id === assetId && p.superseded_at === null)
          .map((p) => p.reference_date)
          .filter((d) => d >= (start as string) && d <= (end as string)),
      ),
    ].sort((a, b) => b.localeCompare(a));
    const items: ReferencePriceDay[] = dates.map((date) => ({
      reference_date: date,
      preferred: preferredOf(assetId, date) as ReferencePrice,
      current: current(assetId, date),
    }));
    return HttpResponse.json<ListResponse<ReferencePriceDay>>({ items });
  }),

  http.get(url('/reference-prices/revisions'), async ({ request }) => {
    await latency();
    const params = new URL(request.url).searchParams;
    const items = db.referencePrices
      .filter(
        (p) =>
          p.asset_id === params.get('asset_id') &&
          p.reference_date === params.get('reference_date'),
      )
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json<ListResponse<ReferencePrice>>({ items });
  }),

  http.post(url('/reference-prices'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    const instrument = findInstrument(body.asset_id);
    const errors: FieldError[] = [];
    if (!instrument)
      errors.push(fieldError('VALIDATION_ERROR', 'Selecione um contrato.', 'asset_id'));
    errors.push(...dateErrors(body.reference_date, 'reference_date'));
    const kind = body.input_kind as InputKind | undefined;
    if (kind === 'PU') errors.push(...decimalErrors(body.pu, 'pu', 10, 'positive'));
    else if (kind === 'RATE') errors.push(...decimalErrors(body.rate, 'rate', 12, 'rate'));
    else errors.push(fieldError('VALIDATION_ERROR', 'Informe o PU ou a taxa.', 'input_kind'));
    if (errors.length > 0 || !instrument || !kind) return problem(422, errors);

    const date = body.reference_date as string;
    const maturity = instrument.maturity_date ?? '9999-12-31';
    if (date > maturity) {
      return problem(422, [
        fieldError('CONTRACT_MATURED', 'O contrato já venceu nesta data.', 'reference_date'),
      ]);
    }
    const days = daysInclusive(date, maturity) - 1;
    if (days === 0 && kind === 'RATE') {
      return problem(422, [
        fieldError('VALIDATION_ERROR', 'Na data de vencimento informe o PU.', 'rate'),
      ]);
    }
    const typed = (kind === 'PU' ? body.pu : body.rate) as string;
    const { pu, rate } = fakePricing(kind, typed, days);

    // A correction supersedes the current MANUAL revision and appends a new one (§5).
    const now = new Date().toISOString();
    const previous = current(instrument.id, date).find((p) => p.source === 'MANUAL');
    if (previous) previous.superseded_at = now;
    const created: ReferencePrice = {
      id: newId(),
      asset_id: instrument.id,
      reference_date: date,
      source: 'MANUAL',
      input_kind: kind,
      pu,
      rate,
      revision: (previous?.revision ?? 0) + 1,
      created_at: now,
      superseded_at: null,
    };
    db.referencePrices.push(created);
    markDirty('valuation', date);
    return HttpResponse.json(created, { status: 201 });
  }),

  http.delete(url('/reference-prices/:id'), async ({ params }) => {
    await latency();
    const price = db.referencePrices.find((p) => p.id === params.id && p.superseded_at === null);
    if (!price) return notFound('Preço de referência');
    price.superseded_at = new Date().toISOString();
    markDirty('valuation', price.reference_date);
    return new HttpResponse(null, { status: 204 });
  }),
];
