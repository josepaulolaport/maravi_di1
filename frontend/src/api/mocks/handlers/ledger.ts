import { http, HttpResponse } from 'msw';

import type { InputKind, CashMovement, FieldError, ListResponse, Trade } from '../../contract';
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

const MOVEMENT_LABELS = { DEPOSIT: 'Aporte', WITHDRAWAL: 'Retirada' } as const;

function inRange(request: Request) {
  const params = new URL(request.url).searchParams;
  const start = params.get('start_date');
  const end = params.get('end_date');
  return { start, end, search: params.get('search'), errors: rangeErrors(start, end) };
}

/** Removes a trade (soft delete in the real backend) and marks accounting dirty. */
function deleteTrade(id: string): boolean {
  const index = db.trades.findIndex((t) => t.id === id);
  const trade = db.trades[index];
  if (!trade) return false;
  db.trades.splice(index, 1);
  markDirty('accounting', trade.trade_date);
  return true;
}

function deleteMovement(id: string): boolean {
  const index = db.cashMovements.findIndex((m) => m.id === id);
  const movement = db.cashMovements[index];
  if (!movement) return false;
  db.cashMovements.splice(index, 1);
  markDirty('accounting', movement.movement_date);
  return true;
}

export const ledgerHandlers = [
  http.get(url('/trades'), async ({ request }) => {
    await latency();
    const { start, end, search, errors } = inRange(request);
    if (errors.length > 0) return problem(422, errors);
    const items = db.trades
      .filter((t) => t.trade_date >= (start as string) && t.trade_date <= (end as string))
      .filter((t) => matches([t.asset_code], search))
      .sort(
        (a, b) =>
          b.trade_date.localeCompare(a.trade_date) ||
          b.trade_time.localeCompare(a.trade_time) ||
          b.seq - a.seq,
      );
    return HttpResponse.json<ListResponse<Trade>>({ items });
  }),

  http.post(url('/trades'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    const instrument = findInstrument(body.asset_id);
    const errors: FieldError[] = [];
    if (!instrument)
      errors.push(fieldError('VALIDATION_ERROR', 'Selecione um contrato.', 'asset_id'));
    errors.push(...dateErrors(body.trade_date, 'trade_date'));
    if (typeof body.trade_time !== 'string' || !/^\d{2}:\d{2}(:\d{2})?$/.test(body.trade_time)) {
      errors.push(fieldError('VALIDATION_ERROR', 'Informe a hora da operação.', 'trade_time'));
    }
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

    const date = body.trade_date as string;
    const maturity = instrument.maturity_date ?? '9999-12-31';
    if (date > maturity) {
      return problem(422, [
        fieldError('CONTRACT_MATURED', 'O contrato já venceu nesta data.', 'trade_date'),
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

    const trade: Trade = {
      id: newId(),
      asset_id: instrument.id,
      asset_code: instrument.code,
      instrument_type_code: 'FUTURE',
      trade_date: date,
      trade_time:
        (body.trade_time as string).length === 5
          ? `${body.trade_time as string}:00`
          : (body.trade_time as string),
      seq: db.nextSeq++,
      signed_quantity: quantity,
      execution_pu: pu,
      execution_rate: rate,
      input_kind: kind,
      // FAKE: float product for the mock only; the backend returns the exact Decimal (§7.3).
      cash_amount: (-quantity * Number(pu)).toFixed(10),
      created_at: new Date().toISOString(),
    };
    db.trades.push(trade);
    markDirty('accounting', date);
    return HttpResponse.json(trade, { status: 201 });
  }),

  http.delete(url('/trades/:id'), async ({ params }) => {
    await latency();
    return deleteTrade(params.id as string)
      ? new HttpResponse(null, { status: 204 })
      : notFound('Lançamento');
  }),

  http.get(url('/cash-movements'), async ({ request }) => {
    await latency();
    const { start, end, search, errors } = inRange(request);
    if (errors.length > 0) return problem(422, errors);
    const items = db.cashMovements
      .filter((m) => m.movement_date >= (start as string) && m.movement_date <= (end as string))
      .filter((m) => matches([m.description, MOVEMENT_LABELS[m.movement_type]], search))
      .sort(
        (a, b) =>
          b.movement_date.localeCompare(a.movement_date) ||
          b.created_at.localeCompare(a.created_at),
      );
    return HttpResponse.json<ListResponse<CashMovement>>({ items });
  }),

  http.post(url('/cash-movements'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    const errors: FieldError[] = [...dateErrors(body.movement_date, 'movement_date')];
    if (body.movement_type !== 'DEPOSIT' && body.movement_type !== 'WITHDRAWAL') {
      errors.push(fieldError('VALIDATION_ERROR', 'Selecione aporte ou retirada.', 'movement_type'));
    }
    errors.push(...decimalErrors(body.amount, 'amount', 2, 'positive'));
    if (errors.length > 0) return problem(422, errors);

    const movement: CashMovement = {
      id: newId(),
      movement_date: body.movement_date as string,
      movement_type: body.movement_type as CashMovement['movement_type'],
      amount: body.amount as string,
      description:
        typeof body.description === 'string' && body.description.trim()
          ? body.description.trim()
          : null,
      created_at: new Date().toISOString(),
    };
    db.cashMovements.push(movement);
    markDirty('accounting', movement.movement_date);
    return HttpResponse.json(movement, { status: 201 });
  }),

  http.delete(url('/cash-movements/:id'), async ({ params }) => {
    await latency();
    return deleteMovement(params.id as string)
      ? new HttpResponse(null, { status: 204 })
      : notFound('Lançamento');
  }),

  // All-or-nothing: if any id is unknown nothing is deleted (§6.1 "operação atômica").
  http.post(url('/ledger/deletions'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    const tradeIds = Array.isArray(body.trade_ids) ? (body.trade_ids as string[]) : [];
    const movementIds = Array.isArray(body.cash_movement_ids)
      ? (body.cash_movement_ids as string[])
      : [];
    if (tradeIds.length + movementIds.length === 0) {
      return problem(422, [fieldError('VALIDATION_ERROR', 'Selecione ao menos um lançamento.')]);
    }
    const unknown =
      tradeIds.some((id) => !db.trades.some((t) => t.id === id)) ||
      movementIds.some((id) => !db.cashMovements.some((m) => m.id === id));
    if (unknown) return notFound('Lançamento');
    tradeIds.forEach(deleteTrade);
    movementIds.forEach(deleteMovement);
    return new HttpResponse(null, { status: 204 });
  }),
];
