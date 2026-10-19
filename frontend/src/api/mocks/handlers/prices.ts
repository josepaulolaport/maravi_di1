import { http, HttpResponse } from 'msw';

import type {
  InputKind,
  FieldError,
  ListResponse,
  ReferencePrice,
  ReferencePriceDay,
} from '../../contract';
import { daysInclusive } from '../dates';
import { db, markChanged, newId } from '../db';
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

/** The price of each source for an asset and date (at most one each). */
const sourcesOf = (assetId: string, date: string) =>
  db.referencePrices.filter((p) => p.asset_id === assetId && p.reference_date === date);

/** MANUAL wins over B3 for the same asset and date (§5). */
export function preferredOf(assetId: string, date: string): ReferencePrice | undefined {
  const observations = sourcesOf(assetId, date);
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
    // Any range, dates after today included: those days have no price (OQ-42).
    const errors = rangeErrors(start, end, { future: 'none' });
    if (!findInstrument(assetId)) {
      errors.push(fieldError('VALIDATION_ERROR', 'Selecione um contrato.', 'asset_id'));
    }
    if (errors.length > 0) return problem(422, errors);

    const dates = [
      ...new Set(
        db.referencePrices
          .filter((p) => p.asset_id === assetId)
          .map((p) => p.reference_date)
          .filter((d) => d >= (start as string) && d <= (end as string)),
      ),
    ].sort((a, b) => b.localeCompare(a));
    const items: ReferencePriceDay[] = dates.map((date) => ({
      reference_date: date,
      preferred: preferredOf(assetId, date) as ReferencePrice,
      sources: sourcesOf(assetId, date),
    }));
    return HttpResponse.json<ListResponse<ReferencePriceDay>>({ items });
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

    // Adding a price deletes the current MANUAL one and inserts the new row, with a new id
    // (OQ-26 item 7); this is how Corrigir works. No revisions (OQ-25).
    db.referencePrices = db.referencePrices.filter(
      (p) => !(p.asset_id === instrument.id && p.reference_date === date && p.source === 'MANUAL'),
    );
    markChanged('price', date);
    const created: ReferencePrice = {
      id: newId(),
      asset_id: instrument.id,
      reference_date: date,
      source: 'MANUAL',
      input_kind: kind,
      pu,
      rate,
      created_at: new Date().toISOString(),
    };
    db.referencePrices.push(created);
    return HttpResponse.json(created, { status: 201 });
  }),

  http.delete(url('/reference-prices/:id'), async ({ params }) => {
    await latency();
    const price = db.referencePrices.find((p) => p.id === params.id);
    if (!price) return notFound('Preço de referência');
    db.referencePrices = db.referencePrices.filter((p) => p !== price);
    markChanged('price', price.reference_date);
    return new HttpResponse(null, { status: 204 });
  }),
];
