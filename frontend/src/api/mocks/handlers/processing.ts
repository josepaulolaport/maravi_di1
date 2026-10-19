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
import { db, isPublished, newId, setStatus, statusOf } from '../db';
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
/** A date written with one of these makes the run end COMPLETED_WITH_ISSUES (OQ-23 item 8). */
const WITH_ISSUES: readonly ChainStatus[] = ['FRESH_WITH_ISSUES', 'STALE'];

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

/** The chain an issue belongs to: a missing price and an expired position are facts of positions. */
function chainOfIssue(issue: (typeof db.issues)[number]): ProcessingChain | null {
  return issue.issue_type === 'STALE_PREDECESSOR' ? issue.chain : 'POSITIONS';
}

/** The date a run processes next: the day after its last commit, or its start. */
const nextDate = (job: ProcessingRequest) =>
  job.progress_date === null ? job.start_date : addDays(job.progress_date, 1);

/**
 * Commits date D of a run, for each chain of its scope, in one step (OQ-23 item 4): publishes
 * D's results, replaces that chain's issues for D (OQ-26 item 5), and sets D's status: FRESH,
 * or FRESH_WITH_ISSUES with a missing price, when D−1 is FRESH, FRESH_WITH_ISSUES or the zero
 * state; otherwise STALE with a STALE_PREDECESSOR issue. Throws for a date the fake cannot
 * compute (its inputs changed since the seed).
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
    const before = predecessorState(date, chain);
    const current = before === 'ZERO_STATE' || before === 'FRESH' || before === 'FRESH_WITH_ISSUES';
    db.issues = db.issues.filter(
      (issue) => !(issue.affected_date === date && chainOfIssue(issue) === chain),
    );
    const issue = (fields: Partial<(typeof db.issues)[number]>) =>
      db.issues.push({
        id: newId(),
        issue_type: 'STALE_PREDECESSOR',
        asset_id: null,
        asset_code: null,
        affected_date: date,
        required_price_date: null,
        chain: null,
        request_id: job.id,
        ...fields,
      });
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
      for (const row of day.positions.items.filter((r) => r.valuation_status === 'MISSING')) {
        missing = true;
        issue({
          issue_type: 'MISSING_REFERENCE_PRICE',
          asset_id: row.asset_id,
          asset_code: row.asset_code,
          required_price_date: date,
        });
      }
    }
    // OQ-11 also asks for null P&L on dates after a stale predecessor. The fake does not
    // enforce it: in this scenario every such date (17/10 on) already has null P&L.
    if (!current) issue({ chain });
    const status: ChainStatus = !current ? 'STALE' : missing ? 'FRESH_WITH_ISSUES' : 'FRESH';
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

/** Marks the next date of a run RUNNING for each chain of its scope (OQ-23 item 4). */
function startDate(job: ProcessingRequest, date: string): void {
  for (const chain of chainsOf(job.scope)) setStatus(date, chain, 'RUNNING');
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
    // OQ-22: cash cannot be carried from a day that has no published cash (with entries on or
    // before it). Checked when the run starts; queuing it was allowed.
    const start = active.start_date;
    const before = addDays(start, -1);
    const refused =
      chainsOf(active.scope).includes('CASH') &&
      !inZeroState(before, 'CASH') &&
      !isPublished(before, 'CASH');
    if (refused) {
      finish(active, {
        status: 'FAILED',
        started_at: now(),
        error_code: 'CASH_PREDECESSOR_MISSING',
        error_message: `O caixa de ${formatDateBr(before)} não foi processado. Processe antes um intervalo que inclua esse dia. Nenhuma data foi publicada.`,
      });
      return;
    }
    Object.assign(active, { status: 'RUNNING', started_at: now(), updated_at: now() });
    startDate(active, start);
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
