import { http, HttpResponse } from 'msw';

import type {
  CashLedgerEntry,
  FieldError,
  InputKind,
  LedgerEntry,
  ListResponse,
  TradeLedgerEntry,
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
  matches,
  notFound,
  problem,
  rangeErrors,
  readJson,
  url,
} from './support';

const TIME = /^\d{2}:\d{2}(:\d{2})?$/;

function inRange(request: Request) {
  const params = new URL(request.url).searchParams;
  const start = params.get('start_date');
  const end = params.get('end_date');
  return { start, end, search: params.get('search'), errors: rangeErrors(start, end) };
}

/** The words a search matches: the contract of a trade; aporte or retirada for cash. */
function searchable(entry: LedgerEntry): string[] {
  if (entry.type === 'TRADE') return [entry.asset_code];
  return [entry.cash_amount.startsWith('-') ? 'Retirada' : 'Aporte'];
}

const compareText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** Newest first, by (date, time, seq), whatever the type (§6.1). */
function compareDescending(a: LedgerEntry, b: LedgerEntry): number {
  return compareText(b.date, a.date) || compareText(b.time, a.time) || b.seq - a.seq;
}

const withSeconds = (time: string) => (time.length === 5 ? `${time}:00` : time);

/** The errors of the fields both types share. */
function commonErrors(body: Record<string, unknown>): FieldError[] {
  const errors = [...dateErrors(body.date, 'date')];
  if (typeof body.time !== 'string' || !TIME.test(body.time)) {
    errors.push(fieldError('VALIDATION_ERROR', 'Informe a hora.', 'time'));
  }
  return errors;
}

function createTrade(body: Record<string, unknown>) {
  const instrument = findInstrument(body.asset_id);
  const errors = commonErrors(body);
  if (!instrument)
    errors.push(fieldError('VALIDATION_ERROR', 'Selecione um contrato.', 'asset_id'));
  if (!Number.isInteger(body.signed_quantity) || body.signed_quantity === 0) {
    errors.push(
      fieldError(
        'VALIDATION_ERROR',
        'A quantidade deve ser um inteiro diferente de zero.',
        'signed_quantity',
      ),
    );
  }
  const kind = body.input_kind as InputKind | undefined;
  if (kind === 'PU')
    errors.push(...decimalErrors(body.execution_pu, 'execution_pu', 10, 'positive'));
  else if (kind === 'RATE')
    errors.push(...decimalErrors(body.execution_rate, 'execution_rate', 12, 'rate'));
  else errors.push(fieldError('VALIDATION_ERROR', 'Informe o PU ou a taxa.', 'input_kind'));
  if (errors.length > 0 || !instrument || !kind) return problem(422, errors);

  const date = body.date as string;
  const maturity = instrument.maturity_date ?? '9999-12-31';
  if (date > maturity) {
    return problem(422, [
      fieldError('CONTRACT_MATURED', 'O contrato já venceu nesta data.', 'date'),
    ]);
  }
  const days = daysInclusive(date, maturity) - 1;
  if (days === 0 && kind === 'RATE') {
    return problem(422, [
      fieldError('VALIDATION_ERROR', 'Na data de vencimento informe o PU.', 'execution_rate'),
    ]);
  }
  const typed = (kind === 'PU' ? body.execution_pu : body.execution_rate) as string;
  const { pu, rate } = fakePricing(kind, typed, days);
  const quantity = body.signed_quantity as number;

  const entry: TradeLedgerEntry = {
    type: 'TRADE',
    id: newId(),
    date,
    time: withSeconds(body.time as string),
    seq: db.nextSeq++,
    asset_id: instrument.id,
    asset_code: instrument.code,
    instrument_type_code: 'FUTURE',
    signed_quantity: quantity,
    execution_pu: pu,
    execution_rate: rate,
    input_kind: kind,
    // FAKE: float product for the mock only; the backend returns the exact Decimal (§7.3).
    cash_amount: (-quantity * Number(pu)).toFixed(10),
    created_at: new Date().toISOString(),
  };
  db.entries.push(entry);
  markDirty('trade', date);
  return HttpResponse.json(entry, { status: 201 });
}

/** Aporte or retirada: a signed amount, at most 2 places, never zero (§6.2, OQ-3). */
function cashAmountErrors(value: unknown): FieldError[] {
  const unsigned = typeof value === 'string' && value.startsWith('-') ? value.slice(1) : value;
  return decimalErrors(unsigned, 'cash_amount', 2, 'positive');
}

function createCash(body: Record<string, unknown>) {
  const errors = [...commonErrors(body), ...cashAmountErrors(body.cash_amount)];
  if (errors.length > 0) return problem(422, errors);
  const entry: CashLedgerEntry = {
    type: 'CASH',
    id: newId(),
    date: body.date as string,
    time: withSeconds(body.time as string),
    seq: db.nextSeq++,
    cash_amount: body.cash_amount as string,
    created_at: new Date().toISOString(),
  };
  db.entries.push(entry);
  markDirty('cash', entry.date);
  return HttpResponse.json(entry, { status: 201 });
}

export const ledgerHandlers = [
  // The Lançamentos list (P18): both types, filtered and ordered here, never in the browser.
  http.get(url('/ledger/entries'), async ({ request }) => {
    await latency();
    const { start, end, search, errors } = inRange(request);
    if (errors.length > 0) return problem(422, errors);
    const order = new URL(request.url).searchParams.get('order') === 'asc' ? 'asc' : 'desc';
    const items = db.entries
      .filter((e) => e.date >= (start as string) && e.date <= (end as string))
      .filter((e) => matches(searchable(e), search))
      .sort(compareDescending);
    if (order === 'asc') items.reverse();
    return HttpResponse.json<ListResponse<LedgerEntry>>({ items });
  }),

  http.post(url('/ledger/entries'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    if (body.type === 'TRADE') return createTrade(body);
    if (body.type === 'CASH') return createCash(body);
    return problem(422, [fieldError('VALIDATION_ERROR', 'Informe o tipo do lançamento.', 'type')]);
  }),

  // All or nothing: if any id is unknown nothing is deleted (§6.1 "operação atômica"). A trade
  // marks cash and positions dirty; a cash entry only cash.
  http.post(url('/ledger/entries/deletions'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    const ids = Array.isArray(body.ids) ? (body.ids as string[]) : [];
    if (ids.length === 0) {
      return problem(422, [fieldError('VALIDATION_ERROR', 'Selecione ao menos um lançamento.')]);
    }
    const found = ids.map((id) => db.entries.find((e) => e.id === id));
    if (found.some((entry) => entry === undefined)) return notFound('Lançamento');
    db.entries = db.entries.filter((e) => !ids.includes(e.id));
    for (const entry of found as LedgerEntry[]) {
      markDirty(entry.type === 'TRADE' ? 'trade' : 'cash', entry.date);
    }
    return new HttpResponse(null, { status: 204 });
  }),
];
