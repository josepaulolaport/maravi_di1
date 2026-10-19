import { http, HttpResponse } from 'msw';

import type {
  CancelAndReplaceResponse,
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
import { db, isPublished, isStale, newId } from '../db';
import {
  FIRST_ENTRY_DATE,
  recalculatedDays,
  summaries,
  positions,
  pnlSeries,
  zeroStateDay,
} from '../fixtures';
import type { RecalculatedDay } from '../fixtures';
import { firstEntryDate } from './portfolio';
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

/** The chains a scope processes (OQ-21 draft). */
export function chainsOf(scope: ProcessingScope): ProcessingChain[] {
  return scope === 'ALL' ? ['CASH', 'POSITIONS'] : [scope];
}

const now = () => new Date().toISOString();

/** State of the day before `start` for one chain (OQ-11), for the preview and the worker. */
function predecessorState(start: string, chain: ProcessingChain): PredecessorState {
  const predecessor = addDays(start, -1);
  const first = firstEntryDate();
  if (first === undefined || predecessor < first) return 'ZERO_STATE';
  if (!isPublished(predecessor, chain)) return 'NOT_PROCESSED';
  return isStale(predecessor, chain) ? 'STALE' : 'VALID';
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
  throw new Error(`The mock scenario has no results for ${date}.`);
}

const formatDateBr = (date: string) => date.split('-').reverse().join('/');

/** Whether a publish of `chains` over [start, end] replaces `issue` with the current ones. */
function replacedBy(
  chains: ProcessingChain[],
  start: string,
  end: string,
  issue: (typeof db.issues)[number],
): boolean {
  if (issue.affected_date < start || issue.affected_date > end) return false;
  if (issue.issue_type === 'MISSING_REFERENCE_PRICE') return chains.includes('POSITIONS');
  if (issue.issue_type === 'STALE_PREDECESSOR') {
    return issue.chain !== null && chains.includes(issue.chain);
  }
  return false;
}

/**
 * Publishes [start, end] for the job's chains all at once (§10.4): the precomputed results of
 * each day, the range's Pendências of those chains replaced by the current ones, and the
 * chains' dirty markers inside the range moved to end + 1 (OQ-12). A stale predecessor, or
 * an unprocessed one for positions, still publishes, and that chain gets a STALE_PREDECESSOR
 * Pendência (OQ-11, OQ-22).
 */
function publish(job: ProcessingRequest): void {
  const start = job.requested_start_date;
  const end = job.requested_end_date;
  const chains = chainsOf(job.scope);
  const publishedAt = now();
  // Every day's results first, so nothing is applied if one is missing (all or nothing).
  const days: [string, RecalculatedDay][] = [];
  for (let date = start; date <= end; date = addDays(date, 1)) {
    days.push([date, structuredClone(precomputedDay(date))]);
  }
  // A missing cash predecessor never gets here (OQ-22: refused at start); a missing
  // positions predecessor still publishes, flagged stale (OQ-11).
  const stalePredecessors = chains.filter((chain) => {
    const state = predecessorState(start, chain);
    return state === 'STALE' || state === 'NOT_PROCESSED';
  });

  db.issues = db.issues.filter((issue) => !replacedBy(chains, start, end, issue));
  for (const [date, day] of days) {
    if (chains.includes('CASH')) {
      db.published.cash.set(date, {
        balance: day.summary.cash_balance,
        trades_cash_flow: day.summary.trades_cash_flow,
        deposits: day.summary.deposits,
        withdrawals: day.summary.withdrawals,
        published_at: publishedAt,
      });
    }
    if (chains.includes('POSITIONS')) {
      db.published.summaries.set(date, { ...day.summary, published_at: publishedAt });
      db.published.positions.set(date, { ...day.positions, published_at: publishedAt });
      db.published.pnl.set(date, day.pnl);
      for (const row of day.positions.items.filter((r) => r.valuation_status === 'MISSING')) {
        db.issues.push({
          id: newId(),
          issue_type: 'MISSING_REFERENCE_PRICE',
          asset_id: row.asset_id,
          asset_code: row.asset_code,
          affected_date: date,
          required_price_date: date,
          chain: null,
          request_id: job.id,
        });
      }
    }
  }
  // OQ-11 also asks for null P&L on days after a stale or missing predecessor. The fake does
  // not enforce it: in this scenario every such day (17/10, 18/10) already has null P&L. A
  // larger scenario would have to null those fields here.
  for (const chain of stalePredecessors) {
    db.issues.push({
      id: newId(),
      issue_type: 'STALE_PREDECESSOR',
      asset_id: null,
      asset_code: null,
      affected_date: start,
      required_price_date: null,
      chain,
      request_id: job.id,
    });
  }
  const markers = [
    ...(chains.includes('CASH') ? (['cash'] as const) : []),
    ...(chains.includes('POSITIONS') ? (['accounting', 'valuation'] as const) : []),
  ];
  for (const kind of markers) {
    const marker = db.dirty[kind];
    if (marker !== null && marker >= start && marker <= end) db.dirty[kind] = addDays(end, 1);
  }
  // Published after a stale or unprocessed day, the chain's days read as stale (OQ-11) until
  // an earlier range is processed: its marker starts at the range.
  for (const chain of stalePredecessors) {
    const kind = chain === 'CASH' ? 'cash' : 'accounting';
    const marker = db.dirty[kind];
    if (marker === null || marker > start) db.dirty[kind] = start;
  }
}

/** The chain each kind of issue belongs to (a missing price and an expired position are facts of positions). */
function chainOf(issue: (typeof db.issues)[number]): ProcessingChain | null {
  if (issue.issue_type === 'STALE_PREDECESSOR') return issue.chain;
  return 'POSITIONS';
}

/** Whether `issue` concerns a job of `chains` over [start, end]. */
function concerns(
  chains: ProcessingChain[],
  start: string,
  end: string,
  issue: (typeof db.issues)[number],
): boolean {
  if (issue.affected_date < start || issue.affected_date > end) return false;
  const chain = chainOf(issue);
  return chain !== null && chains.includes(chain);
}

/**
 * Advances the fake worker one step per poll, so the UI can show every status:
 * QUEUED → DISPATCHED → RUNNING (one day per poll) → COMPLETED / COMPLETED_WITH_ISSUES /
 * SUPERSEDED / FAILED, and CANCELLING → CANCELLED. Only one job is active at a time (§10.2).
 *
 * The fake cannot recalculate: a finished job publishes the scenario's precomputed results
 * for its scope. When a write since the seed touched a day one of its chains depends on (any
 * day up to the range's end), those results would be wrong, so the job fails and publishes
 * nothing; only the real backend can recalculate them.
 */
function tick(): void {
  const active = db.requests.find((r) => ACTIVE.includes(r.status));
  if (active?.status === 'CANCELLING') {
    Object.assign(active, { status: 'CANCELLED', finished_at: now(), progress_date: null });
    return;
  }
  if (active?.status === 'DISPATCHED') {
    // OQ-22: cash cannot be carried from a day that has no published cash (with entries
    // before it). Checked when the job starts; queuing it was allowed.
    const start = active.requested_start_date;
    if (
      chainsOf(active.scope).includes('CASH') &&
      predecessorState(start, 'CASH') === 'NOT_PROCESSED'
    ) {
      Object.assign(active, {
        status: 'FAILED',
        started_at: now(),
        finished_at: now(),
        error_code: 'CASH_PREDECESSOR_MISSING',
        error_message: `O caixa de ${formatDateBr(addDays(start, -1))} não foi processado. Processe antes um intervalo que inclua esse dia. Nenhum dia foi publicado.`,
      });
      return;
    }
    Object.assign(active, {
      status: 'RUNNING',
      started_at: now(),
      progress_date: active.requested_start_date,
    });
    db.startRevision.set(active.id, { ...db.revision });
    return;
  }
  if (active?.status === 'RUNNING') {
    active.processed_days += 1;
    if (active.processed_days < active.total_days) {
      active.progress_date = addDays(active.requested_start_date, active.processed_days);
      return;
    }
    const finished = { finished_at: now(), progress_date: null };
    const chains = chainsOf(active.scope);
    const seen = db.startRevision.get(active.id);
    // An input of one of its chains changed during the run: publishing would overwrite
    // current data (§10.2). Writes that only change the other chain do not concern it.
    if (chains.some((chain) => db.revision[chain] !== seen?.[chain])) {
      Object.assign(active, { status: 'SUPERSEDED', ...finished });
      return;
    }
    const start = active.requested_start_date;
    const end = active.requested_end_date;
    const changed = chains
      .map((chain) => db.changedFrom[chain])
      .filter((date): date is string => date !== null && date <= end)
      .sort()
      .at(0);
    if (changed !== undefined) {
      Object.assign(active, {
        status: 'FAILED',
        ...finished,
        error_code: 'MOCK_INPUTS_CHANGED',
        error_message: `Backend simulado: os resultados a partir de ${formatDateBr(changed)} dependem de lançamentos ou preços alterados e só podem ser recalculados pelo backend real. Nenhum dia foi publicado.`,
      });
      return;
    }
    publish(active);
    const withIssues = db.issues.some((issue) => concerns(chains, start, end, issue));
    Object.assign(active, {
      status: withIssues ? 'COMPLETED_WITH_ISSUES' : 'COMPLETED',
      ...finished,
    });
    return;
  }
  const next = db.requests
    .filter((r) => r.status === 'QUEUED')
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
    .at(0);
  if (next) Object.assign(next, { status: 'DISPATCHED', dispatched_at: now() });
}

function enqueue(start: string, end: string, scope: ProcessingScope): ProcessingRequest {
  const request: ProcessingRequest = {
    id: newId(),
    requested_start_date: start,
    requested_end_date: end,
    scope,
    status: 'QUEUED',
    created_at: now(),
    dispatched_at: null,
    started_at: null,
    finished_at: null,
    cancel_requested_at: null,
    processed_days: 0,
    total_days: daysInclusive(start, end),
    progress_date: null,
    error_code: null,
    error_message: null,
  };
  db.requests.push(request);
  return request;
}

/** Cancels a job: a queued one at once, a running one cooperatively (§10.2). */
function cancel(request: ProcessingRequest): ProcessingRequest {
  request.cancel_requested_at = now();
  if (request.status === 'QUEUED') {
    Object.assign(request, { status: 'CANCELLED', finished_at: now() });
  } else {
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

/** A request's range and scope (OQ-21 draft: the scope is required). */
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

  http.post(url('/processing/requests/:id/cancel-and-replace'), async ({ params, request }) => {
    await latency();
    const body = await readJson(request);
    const errors = requestErrors(body.start_date, body.end_date, body.scope);
    if (errors.length > 0) return problem(422, errors);
    const active = db.requests.find((r) => r.id === params.id);
    if (!active) return notFound('Processamento');
    if (!CANCELLABLE.includes(active.status)) return notCancellable();
    const response: CancelAndReplaceResponse = {
      cancelled: cancel(active),
      replacement: enqueue(
        body.start_date as string,
        body.end_date as string,
        body.scope as ProcessingScope,
      ),
    };
    return HttpResponse.json(response, { status: 201 });
  }),

  http.get(url('/processing/issues'), async () => {
    await latency();
    const items = [...db.issues].sort((a, b) => b.affected_date.localeCompare(a.affected_date));
    return HttpResponse.json({ items });
  }),
];
