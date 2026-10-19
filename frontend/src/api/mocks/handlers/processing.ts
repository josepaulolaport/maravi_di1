import { http, HttpResponse } from 'msw';

import type {
  FieldError,
  Issue,
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

const SCOPES: readonly ProcessingScope[] = ['CASH', 'POSITIONS', 'ALL'];
/** A date written with this makes the run end COMPLETED_WITH_ISSUES (OQ-23 item 8, OQ-31). */
const WITH_ISSUES: readonly ChainStatus[] = ['PROCESSED_WITH_ISSUES'];

/** The chains a scope processes (OQ-21). */
export function chainsOf(scope: ProcessingScope): ProcessingChain[] {
  return scope === 'ALL' ? ['CASH', 'POSITIONS'] : [scope];
}

const now = () => new Date().toISOString();

const isProcessed = (status: PredecessorState) =>
  status === 'PROCESSED' || status === 'PROCESSED_WITH_ISSUES';

/**
 * Whether a chain is in its zero state after `date`, the day before the one processed (OQ-40
 * item 5): no date up to it has any status for the chain, and no entry of the chain's type is
 * dated on or before it (positions: a trade; cash: an entry of either type, OQ-26 item 3).
 */
function inZeroState(date: string, chain: ProcessingChain): boolean {
  for (const [day, row] of db.dateStatus) {
    if (day <= date && row[chain] !== null) return false;
  }
  return !db.entries.some((e) => e.date <= date && (chain === 'CASH' || e.type === 'TRADE'));
}

/** The day before `start` for one chain (OQ-11, OQ-26): its status, or the zero state. */
function predecessorState(start: string, chain: ProcessingChain): PredecessorState {
  const predecessor = addDays(start, -1);
  const status = statusOf(predecessor, chain);
  if (status !== 'NOT_PROCESSED') return status;
  return inZeroState(predecessor, chain) ? 'ZERO_STATE' : status;
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
 * The chains a run still processes: its scope's, less the one that failed (OQ-36 item 1). A run
 * whose every chain failed has ended.
 */
const aliveChains = (job: ProcessingRequest): ProcessingChain[] =>
  chainsOf(job.scope).filter((chain) => chain !== job.failed_chain);

/**
 * Records a failure of `chains` on `date` (OQ-36, OQ-40 item 3): each reads Erro on the date
 * and stops; the run keeps its first failure's code, message, date and chain (POSITIONS when
 * both fail at once). Returns whether a chain is still alive, so the run goes on.
 */
function failChains(
  job: ProcessingRequest,
  date: string,
  chains: ProcessingChain[],
  error: { code: string; message: string },
): boolean {
  const alive = aliveChains(job);
  for (const chain of chains) setStatus(date, chain, 'FAILED');
  // The first failure stays; when cash failed earlier on this same date and positions fail now,
  // the positions error is the one kept (OQ-36 item 5, OQ-40 item 3).
  const samePositionsDate =
    job.failed_date === date && job.failed_chain === 'CASH' && chains.includes('POSITIONS');
  if (job.failed_date === null || samePositionsDate) {
    Object.assign(job, {
      error_code: error.code,
      error_message: error.message,
      failed_date: date,
      failed_chain: chains.includes('POSITIONS') ? 'POSITIONS' : chains[0],
    });
  }
  const survivors = alive.filter((chain) => !chains.includes(chain));
  if (survivors.length === 0) {
    finish(job, { status: 'FAILED', ...(job.started_at === null ? { started_at: now() } : {}) });
  }
  return survivors.length > 0;
}

/**
 * Commits date D of a run, for each chain it still processes, in one step (OQ-23 item 4):
 * publishes D's results (their `published_at` is the chain's processing time, OQ-31), replaces
 * D's Pendências (OQ-26 item 5; both issue types are facts of positions) and sets D PROCESSED,
 * or PROCESSED_WITH_ISSUES with a missing price. A chain the fake cannot compute on D (its
 * inputs changed since the seed) fails there; the others commit D (OQ-36 item 8). Returns
 * whether a chain is still alive. The predecessor was checked when D started.
 */
function commitDate(job: ProcessingRequest, date: string): boolean {
  const changed = aliveChains(job).filter((chain) => {
    const from = db.changedFrom[chain];
    return from !== null && date >= from;
  });
  if (
    changed.length > 0 &&
    !failChains(job, date, changed, {
      code: 'MOCK_INPUTS_CHANGED',
      message: `Backend simulado: ${formatDateBr(date)} depende de lançamentos ou preços alterados e só pode ser recalculado pelo backend real. As datas anteriores continuam publicadas.`,
    })
  ) {
    return false;
  }
  const chains = aliveChains(job);

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
  // AUM follows the other chain's status on the date, whichever run wrote it (OQ-38, OQ-40):
  // with both chains written here, both are processed now.
  const other = (['CASH', 'POSITIONS'] as const).find((chain) => !chains.includes(chain));
  db.published.aum.set(
    date,
    other === undefined || isProcessed(statusOf(date, other)) ? day.summary.aum : null,
  );
  db.written.set(job.id, statuses);
  Object.assign(job, { progress_date: date, updated_at: now() });
  return true;
}

/**
 * Starts date D of a run (OQ-23 item 4, OQ-31 item 4): for each chain it still processes, D−1
 * must be PROCESSED, PROCESSED_WITH_ISSUES or the chain's zero state. A failing chain reads Erro
 * on D and stops (POSITIONS_… when both fail, OQ-36 item 5); on an ALL run the other chain goes
 * on (OQ-36 items 1 and 8), and the run ends FAILED only when no chain is left. The fake checks
 * before marking D RUNNING, so a failing chain never reads Processando. Returns whether D
 * started.
 */
function startDate(job: ProcessingRequest, date: string): boolean {
  const failing = aliveChains(job).filter((chain) => !isProcessedOrZero(date, chain));
  if (
    failing.length > 0 &&
    !failChains(job, date, failing, {
      code: failing.includes('POSITIONS')
        ? 'POSITIONS_PREDECESSOR_MISSING'
        : 'CASH_PREDECESSOR_MISSING',
      message: 'Dia anterior não processado',
    })
  ) {
    return false;
  }
  for (const chain of aliveChains(job)) setStatus(date, chain, 'RUNNING');
  return true;
}

/** Whether D−1 lets a chain process D (OQ-31 item 4). */
function isProcessedOrZero(date: string, chain: ProcessingChain): boolean {
  const before = predecessorState(date, chain);
  return before === 'ZERO_STATE' || isProcessed(before);
}

function finish(job: ProcessingRequest, fields: Partial<ProcessingRequest>): void {
  Object.assign(job, { finished_at: now(), updated_at: now(), ...fields });
}

/**
 * Advances the fake worker one step per read of the job list or a job, so the UI can show
 * every status (one active run at a time, §10.2): QUEUED → RUNNING (no dispatcher, OQ-46), then
 * one date per step, each published as it commits (OQ-23). A cancel is checked between dates: the date
 * being processed commits, later dates are untouched, and the run ends CANCELLED, or as it
 * would have when that date was its last (OQ-26 item 9). A failure at a date sets it FAILED for
 * the failing chain and keeps every earlier date published (OQ-23 item 5). On an ALL run the
 * other chain goes on to the end and the run ends COMPLETED_WITH_ISSUES with the first failure,
 * or CANCELLED keeping it; the run ends FAILED only when every chain failed (OQ-36, OQ-40).
 *
 * The fake cannot recalculate: a date publishes the scenario's precomputed results. A date on
 * or after a write since the seed (in a chain of the run) would get wrong results, so it fails
 * there; only the real backend can recalculate it.
 */
function tick(): void {
  const active = db.requests.find((r) => r.status === 'RUNNING');
  if (active) {
    const date = nextDate(active);
    if (!commitDate(active, date)) return;
    if (date >= active.end_date) {
      // A chain that failed while the other reached the end also leaves issues (OQ-36 item 4).
      const issues =
        active.failed_date !== null ||
        (db.written.get(active.id) ?? []).some((s) => WITH_ISSUES.includes(s));
      finish(active, { status: issues ? 'COMPLETED_WITH_ISSUES' : 'COMPLETED' });
      return;
    }
    if (active.cancel_requested_at !== null) {
      finish(active, { status: 'CANCELLED' });
      return;
    }
    startDate(active, addDays(date, 1));
    return;
  }
  // No dispatcher (OQ-46): the one worker takes the oldest queued run, by (created_at, id),
  // straight to RUNNING and starts its first date.
  const next = db.requests
    .filter((r) => r.status === 'QUEUED')
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
    .at(0);
  if (!next) return;
  Object.assign(next, { status: 'RUNNING', started_at: now(), updated_at: now() });
  startDate(next, next.start_date);
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
    failed_date: null,
    failed_chain: null,
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

/**
 * Cancels a run (§10.2, OQ-46): a queued one at once; a running one cooperatively, between
 * dates. A running run stays RUNNING with `cancel_requested_at` set: there is no CANCELLING.
 */
function cancel(request: ProcessingRequest): ProcessingRequest {
  Object.assign(request, { cancel_requested_at: now(), updated_at: now() });
  if (request.status === 'QUEUED') {
    Object.assign(request, { status: 'CANCELLED', finished_at: now() });
  }
  return request;
}

const notCancellable = (message: string) =>
  problem(409, [fieldError('JOB_NOT_CANCELLABLE', message)]);

/** A request's range and scope (OQ-21: the scope is required). */
function requestErrors(start: unknown, end: unknown, scope: unknown): FieldError[] {
  const errors = rangeErrors(start, end);
  if (!SCOPES.includes(scope as ProcessingScope)) {
    errors.push(fieldError('VALIDATION_ERROR', 'Selecione o escopo do processamento.', 'scope'));
  }
  return errors;
}

/**
 * Pendências are deduplicated on read (OQ-37 item 1): a missing price once per (asset, needed
 * date), an expired open position once per asset, each at its earliest affected date.
 */
function deduplicated(issues: Issue[]): Issue[] {
  const byObligation = new Map<string, Issue>();
  for (const issue of issues) {
    const key =
      issue.issue_type === 'MISSING_REFERENCE_PRICE'
        ? `${issue.issue_type}|${issue.asset_id ?? ''}|${issue.required_price_date ?? ''}`
        : `${issue.issue_type}|${issue.asset_id ?? ''}`;
    const kept = byObligation.get(key);
    if (!kept || issue.affected_date < kept.affected_date) byObligation.set(key, issue);
  }
  return [...byObligation.values()];
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
    if (request.status !== 'QUEUED' && request.status !== 'RUNNING') {
      return notCancellable('Este processamento já foi encerrado e não pode ser cancelado.');
    }
    if (request.cancel_requested_at !== null) {
      return notCancellable('O cancelamento deste processamento já foi solicitado.');
    }
    return HttpResponse.json(cancel(request));
  }),

  http.get(url('/processing/issues'), async () => {
    await latency();
    const items = deduplicated(db.issues).sort((a, b) =>
      b.affected_date.localeCompare(a.affected_date),
    );
    return HttpResponse.json({ items });
  }),
];
