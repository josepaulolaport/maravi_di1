import { http, HttpResponse } from 'msw';

import type {
  FieldError,
  JobStatus,
  Page,
  PredecessorState,
  ProcessingChain,
  ProcessingPreview,
  ProcessingRequest,
  ProcessingScope,
} from '../../contract';
import { addDays, daysInclusive } from '../dates';
import { db, newId, setStatus, statusOf } from '../db';
import type { ChainStatus } from '../db';
import {
  dayWithoutInputs,
  FIRST_ENTRY_DATE,
  recalculatedDays,
  summaries,
  positions,
  pnlSeries,
  zeroStateDay,
} from '../fixtures';
import type { RecalculatedDay } from '../fixtures';
import {
  fieldError,
  latency,
  notFound,
  paginate,
  problem,
  rangeErrors,
  readJson,
  url,
} from './support';

const ACTIVE: JobStatus[] = ['DISPATCHED', 'RUNNING', 'CANCELLING'];
const CANCELLABLE: JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING'];
const SCOPES: readonly ProcessingScope[] = ['CASH', 'POSITIONS', 'ALL'];
/** A date written with this makes the run end COMPLETED_WITH_ISSUES (OQ-23 item 8, OQ-31). */
const WITH_ISSUES: readonly ChainStatus[] = ['PROCESSED_WITH_ISSUES'];

/** The chains a scope processes (OQ-21). */
export function chainsOf(scope: ProcessingScope): ProcessingChain[] {
  return scope === 'ALL' ? ['CASH', 'POSITIONS'] : [scope];
}

const now = () => new Date().toISOString();

/**
 * Whether a chain is in its zero state on `date` (OQ-26 item 3): positions, when no trade is
 * dated on or before it; cash, when no entry of either type is.
 */
function inZeroState(date: string, chain: ProcessingChain): boolean {
  return !db.entries.some((e) => e.date <= date && (chain === 'CASH' || e.type === 'TRADE'));
}

/** The day before `start` for one chain (OQ-11, OQ-26): its status, or the zero state. */
function predecessorState(start: string, chain: ProcessingChain): PredecessorState {
  const predecessor = addDays(start, -1);
  return inZeroState(predecessor, chain) ? 'ZERO_STATE' : statusOf(predecessor, chain);
}

/** The scenario's results for `date`, valid only while its inputs are unchanged. */
function precomputedDay(date: string): RecalculatedDay {
  const recalculated = recalculatedDays[date];
  if (recalculated) return recalculated;
  const summary = summaries.find((s) => s.date === date);
  const rows = positions.find((p) => p.date === date);
  const point = pnlSeries.find((p) => p.date === date);
  if (summary && rows && point) return { summary, positions: rows, pnl: point };
  if (date < FIRST_ENTRY_DATE) return zeroStateDay(date);
  return dayWithoutInputs(date);
}

const formatDateBr = (date: string) => date.split('-').reverse().join('/');

/** The date a run processes next: the day after its last commit, or its start. */
const nextDate = (job: ProcessingRequest) =>
  job.progress_date === null ? job.start_date : addDays(job.progress_date, 1);

/**
 * Commits date D of a run, for each chain of its scope, in one step (OQ-23 item 4): publishes
 * D's results (their `published_at` is the chain's processing time, OQ-31), replaces D's
 * Pendências (OQ-26 item 5; both issue types are facts of positions) and sets D PROCESSED, or
 * PROCESSED_WITH_ISSUES with a missing price. Throws for a date the fake cannot compute (its
 * inputs changed since the seed). The predecessor was checked when D started.
 */
function commitDate(job: ProcessingRequest, date: string): void {
  const chains = chainsOf(job.scope);
  const changed = chains.find((chain) => {
    const from = db.changedFrom[chain];
    return from !== null && date >= from;
  });
  if (changed !== undefined) throw new MockCannotCompute(date);

  const day = structuredClone(precomputedDay(date));
  const publishedAt = now();
  const statuses = db.written.get(job.id) ?? [];
  for (const chain of chains) {
    let missing = false;
    if (chain === 'CASH') {
      db.published.cash.set(date, {
        balance: day.summary.cash_balance,
        trades_cash_flow: day.summary.trades_cash_flow,
        deposits: day.summary.deposits,
        withdrawals: day.summary.withdrawals,
        published_at: publishedAt,
      });
    } else {
      db.published.summaries.set(date, { ...day.summary, published_at: publishedAt });
      db.published.positions.set(date, { ...day.positions, published_at: publishedAt });
      db.published.pnl.set(date, day.pnl);
      db.issues = db.issues.filter((issue) => issue.affected_date !== date);
      for (const row of day.positions.items.filter((r) => r.valuation_status === 'MISSING')) {
        missing = true;
        db.issues.push({
          id: newId(),
          issue_type: 'MISSING_REFERENCE_PRICE',
          asset_id: row.asset_id,
          asset_code: row.asset_code,
          affected_date: date,
          required_price_date: date,
          request_id: job.id,
        });
      }
    }
    const status: ChainStatus = missing ? 'PROCESSED_WITH_ISSUES' : 'PROCESSED';
    setStatus(date, chain, status);
    statuses.push(status);
  }
  db.written.set(job.id, statuses);
  Object.assign(job, { progress_date: date, updated_at: now() });
}

/** The fake has no engine: a date whose inputs changed since the seed cannot be computed. */
class MockCannotCompute extends Error {
  constructor(readonly date: string) {
    super(date);
  }
}

/**
 * Starts date D of a run (OQ-23 item 4, OQ-31 item 4): for each chain of its scope, D−1 must be
 * PROCESSED, PROCESSED_WITH_ISSUES or the chain's zero state. Otherwise nothing is written for
 * D: each failing chain's D reads Erro, the run ends FAILED with that chain's error code
 * (POSITIONS_… when both fail, OQ-31 item 7) and later dates are untouched. The fake checks
 * before marking D RUNNING, so the other chain keeps its status as the backend puts it back.
 * Returns whether D started.
 */
function startDate(job: ProcessingRequest, date: string): boolean {
  const chains = chainsOf(job.scope);
  const failing = chains.filter((chain) => {
    const before = predecessorState(date, chain);
    return before !== 'ZERO_STATE' && before !== 'PROCESSED' && before !== 'PROCESSED_WITH_ISSUES';
  });
  if (failing.length > 0) {
    for (const chain of failing) setStatus(date, chain, 'FAILED');
    finish(job, {
      status: 'FAILED',
      ...(job.started_at === null ? { started_at: now() } : {}),
      error_code: failing.includes('POSITIONS')
        ? 'POSITIONS_PREDECESSOR_MISSING'
        : 'CASH_PREDECESSOR_MISSING',
      error_message: 'Dia anterior não processado',
    });
    return false;
  }
  for (const chain of chains) setStatus(date, chain, 'RUNNING');
  return true;
}

function finish(job: ProcessingRequest, fields: Partial<ProcessingRequest>): void {
  Object.assign(job, { finished_at: now(), updated_at: now(), ...fields });
}

/**
 * Advances the fake worker one step per read of the job list or a job, so the UI can show
 * every status (one active run at a time, §10.2): QUEUED → DISPATCHED → RUNNING, then one date
 * per step, each published as it commits (OQ-23). A cancel is checked between dates: the date
 * being processed commits, later dates are untouched, and the run ends CANCELLED, or as it
 * would have when that date was its last (OQ-26 item 9). A failure at a date sets it FAILED,
 * keeps every earlier date published and ends the run FAILED (OQ-23 item 5).
 *
 * The fake cannot recalculate: a date publishes the scenario's precomputed results. A date on
 * or after a write since the seed (in a chain of the run) would get wrong results, so it fails
 * there; only the real backend can recalculate it.
 */
function tick(): void {
  const active = db.requests.find((r) => ACTIVE.includes(r.status));
  if (active?.status === 'DISPATCHED') {
    if (!startDate(active, active.start_date)) return;
    Object.assign(active, { status: 'RUNNING', started_at: now(), updated_at: now() });
    return;
  }
  if (active?.status === 'CANCELLING' && active.started_at === null) {
    // Cancelled while dispatched (GAP-G-2): it ends without running a date.
    finish(active, { status: 'CANCELLED' });
    return;
  }
  if (active?.status === 'RUNNING' || active?.status === 'CANCELLING') {
    const date = nextDate(active);
    try {
      commitDate(active, date);
    } catch (error) {
      if (!(error instanceof MockCannotCompute)) throw error;
      for (const chain of chainsOf(active.scope)) setStatus(date, chain, 'FAILED');
      finish(active, {
        status: 'FAILED',
        error_code: 'MOCK_INPUTS_CHANGED',
        error_message: `Backend simulado: ${formatDateBr(date)} depende de lançamentos ou preços alterados e só pode ser recalculado pelo backend real. As datas anteriores continuam publicadas.`,
      });
      return;
    }
    if (date >= active.end_date) {
      const issues = (db.written.get(active.id) ?? []).some((s) => WITH_ISSUES.includes(s));
      finish(active, { status: issues ? 'COMPLETED_WITH_ISSUES' : 'COMPLETED' });
      return;
    }
    if (active.status === 'CANCELLING') {
      finish(active, { status: 'CANCELLED' });
      return;
    }
    startDate(active, addDays(date, 1));
    return;
  }
  const next = db.requests
    .filter((r) => r.status === 'QUEUED')
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
    .at(0);
  if (next) Object.assign(next, { status: 'DISPATCHED', dispatched_at: now(), updated_at: now() });
}

function enqueue(start: string, end: string, scope: ProcessingScope): ProcessingRequest {
  const created = now();
  const request: ProcessingRequest = {
    id: newId(),
    scope,
    start_date: start,
    end_date: end,
    status: 'QUEUED',
    progress_date: null,
    error_code: null,
    error_message: null,
    created_at: created,
    updated_at: created,
    dispatched_at: null,
    started_at: null,
    finished_at: null,
    cancel_requested_at: null,
  };
  db.requests.push(request);
  return request;
}

/** Cancels a run: a queued one at once, a started one cooperatively, between dates (§10.2). */
function cancel(request: ProcessingRequest): ProcessingRequest {
  Object.assign(request, { cancel_requested_at: now(), updated_at: now() });
  if (request.status === 'QUEUED') {
    Object.assign(request, { status: 'CANCELLED', finished_at: now() });
  } else {
    // DISPATCHED (GAP-G-2) or RUNNING: cooperative, it ends at the next safe point.
    request.status = 'CANCELLING';
  }
  return request;
}

const notCancellable = () =>
  problem(409, [
    fieldError(
      'JOB_NOT_CANCELLABLE',
      'Este processamento já foi encerrado e não pode ser cancelado.',
    ),
  ]);

/** A request's range and scope (OQ-21: the scope is required). */
function requestErrors(start: unknown, end: unknown, scope: unknown): FieldError[] {
  const errors = rangeErrors(start, end);
  if (!SCOPES.includes(scope as ProcessingScope)) {
    errors.push(fieldError('VALIDATION_ERROR', 'Selecione o escopo do processamento.', 'scope'));
  }
  return errors;
}

export const processingHandlers = [
  // Newest first, by (created_at, id), paged by keyset (P21).
  http.get(url('/processing/requests'), async ({ request }) => {
    await latency();
    tick();
    const items = [...db.requests].sort(
      (a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id),
    );
    const page = paginate(items, request);
    return page instanceof Response ? page : HttpResponse.json<Page<ProcessingRequest>>(page);
  }),

  http.get(url('/processing/requests/:id'), async ({ params }) => {
    await latency();
    tick();
    const request = db.requests.find((r) => r.id === params.id);
    return request ? HttpResponse.json(request) : notFound('Processamento');
  }),

  http.get(url('/processing/preview'), async ({ request }) => {
    await latency();
    const params = new URL(request.url).searchParams;
    const start = params.get('start_date');
    const end = params.get('end_date');
    const scope = params.get('scope');
    const errors = requestErrors(start, end, scope);
    if (errors.length > 0 || !start || !end) return problem(422, errors);

    return HttpResponse.json<ProcessingPreview>({
      start_date: start,
      end_date: end,
      total_days: daysInclusive(start, end),
      scope: scope as ProcessingScope,
      predecessor_date: addDays(start, -1),
      predecessor: {
        cash: predecessorState(start, 'CASH'),
        positions: predecessorState(start, 'POSITIONS'),
      },
    });
  }),

  http.post(url('/processing/requests'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    const errors = requestErrors(body.start_date, body.end_date, body.scope);
    if (errors.length > 0) return problem(422, errors);
    return HttpResponse.json(
      enqueue(body.start_date as string, body.end_date as string, body.scope as ProcessingScope),
      { status: 201 },
    );
  }),

  http.post(url('/processing/requests/:id/cancel'), async ({ params }) => {
    await latency();
    const request = db.requests.find((r) => r.id === params.id);
    if (!request) return notFound('Processamento');
    if (!CANCELLABLE.includes(request.status)) return notCancellable();
    return HttpResponse.json(cancel(request));
  }),

  http.get(url('/processing/issues'), async () => {
    await latency();
    const items = [...db.issues].sort((a, b) => b.affected_date.localeCompare(a.affected_date));
    return HttpResponse.json({ items });
  }),
];
