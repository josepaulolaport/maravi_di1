import { http, HttpResponse } from 'msw';

import type { Instrument, LastReference, ListResponse, Product } from '../../contract';
import { db, newId } from '../db';
import { instrumentTypes, products } from '../fixtures';
import { preferredOf } from './prices';
import { isIsoDate } from '../dates';
import {
  fieldError,
  findInstrument,
  latency,
  matches,
  notFound,
  problem,
  readJson,
  url,
} from './support';

function lastReference(assetId: string): LastReference | null {
  const dates = [
    ...new Set(
      db.referencePrices
        .filter((p) => p.asset_id === assetId && p.superseded_at === null)
        .map((p) => p.reference_date),
    ),
  ].sort();
  const latest = dates.at(-1);
  if (!latest) return null;
  const preferred = preferredOf(assetId, latest);
  return preferred
    ? {
        reference_date: preferred.reference_date,
        pu: preferred.pu,
        rate: preferred.rate,
        source: preferred.source,
      }
    : null;
}

function toInstrument(instrument: (typeof db.instruments)[number]): Instrument {
  return { ...instrument, last_reference: lastReference(instrument.id) };
}

function withCount(product: Product): Product {
  return {
    ...product,
    instrument_count: db.instruments.filter((i) => i.product_id === product.id).length,
  };
}

export const assetHandlers = [
  http.get(url('/instrument-types'), async () => {
    await latency();
    return HttpResponse.json({ items: instrumentTypes });
  }),

  http.get(url('/products'), async ({ request }) => {
    await latency();
    const params = new URL(request.url).searchParams;
    const type = params.get('instrument_type');
    const items = products
      .filter((p) => !type || p.instrument_type.code === type)
      .filter((p) => matches([p.code, p.name, p.asset_class.name], params.get('search')))
      .map(withCount);
    return HttpResponse.json<ListResponse<Product>>({ items });
  }),

  http.get(url('/products/:id'), async ({ params }) => {
    await latency();
    const product = products.find((p) => p.id === params.id);
    return product ? HttpResponse.json(withCount(product)) : notFound('Produto');
  }),

  http.get(url('/instruments'), async ({ request }) => {
    await latency();
    const params = new URL(request.url).searchParams;
    const productId = params.get('product_id');
    const items = db.instruments
      .filter((i) => !productId || i.product_id === productId)
      .filter((i) => matches([i.code], params.get('search')))
      .sort((a, b) => (a.maturity_date ?? '').localeCompare(b.maturity_date ?? ''))
      .map(toInstrument);
    return HttpResponse.json<ListResponse<Instrument>>({ items });
  }),

  http.get(url('/instruments/:id'), async ({ params }) => {
    await latency();
    const instrument = findInstrument(params.id);
    return instrument ? HttpResponse.json(toInstrument(instrument)) : notFound('Contrato');
  }),

  http.post(url('/instruments'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    const product = products.find((p) => p.id === body.product_id);
    const code = typeof body.code === 'string' ? body.code.trim().toUpperCase() : '';
    const errors = [];
    if (!product)
      errors.push(fieldError('VALIDATION_ERROR', 'Selecione um produto.', 'product_id'));
    if (!code) errors.push(fieldError('VALIDATION_ERROR', 'Informe o código do contrato.', 'code'));
    else if (db.instruments.some((i) => i.code.toUpperCase() === code)) {
      errors.push(fieldError('VALIDATION_ERROR', 'Já existe um contrato com este código.', 'code'));
    }
    if (!isIsoDate(body.maturity_date)) {
      errors.push(fieldError('VALIDATION_ERROR', 'Informe o vencimento.', 'maturity_date'));
    }
    if (errors.length > 0 || !product) return problem(422, errors);

    const instrument = {
      id: newId(),
      code,
      product_id: product.id,
      product_code: product.code,
      maturity_date: body.maturity_date as string,
      created_at: new Date().toISOString(),
    };
    db.instruments.push(instrument);
    return HttpResponse.json(toInstrument(instrument), { status: 201 });
  }),
];
