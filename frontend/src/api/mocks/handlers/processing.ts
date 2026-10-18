import { http, HttpResponse } from 'msw';

import type {
  CancelAndReplaceResponse,
  JobStatus,
  ListResponse,
  ProcessingPreview,
  ProcessingRequest,
} from '../../contract';
import { addDays, daysInclusive } from '../dates';
import { db, isStale, newId } from '../db';
import { firstEntryDate, isPublished } from './portfolio';
import { fieldError, latency, notFound, problem, rangeErrors, readJson, url } from './support';

const ACTIVE: JobStatus[] = ['DISPATCHED', 'RUNNING', 'CANCELLING'];
const CANCELLABLE: JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING'];

const now = () => new Date().toISOString();

/** State of the day before `start` (OQ-11), shared by the preview and the fake worker. */
function predecessorState(start: string): ProcessingPreview['predecessor_state'] {
  const predecessor = addDays(start, -1);
  const first = firstEntryDate();
  if (first === undefined || predecessor < first) return 'ZERO_STATE';
  if (!isPublished(predecessor)) return 'NOT_PROCESSED';
  return isStale(predecessor) ? 'STALE' : 'VALID';
}

/**
 * Advances the fake worker one step per poll, so the UI can show every status:
 * QUEUED → DISPATCHED → RUNNING (one day per poll) → COMPLETED / COMPLETED_WITH_ISSUES /
 * SUPERSEDED, and CANCELLING → CANCELLED. Only one job is active at a time (§10.2).
 *
 * The fake cannot recalculate, so a finished job publishes nothing new and leaves the dirty
 * markers as they are; the real backend republishes and advances them (OQ-12).
 */
function tick(): void {
  const active = db.requests.find((r) => ACTIVE.includes(r.status));
  if (active?.status === 'CANCELLING') {
    Object.assign(active, { status: 'CANCELLED', finished_at: now(), progress_date: null });
    return;
  }
  if (active?.status === 'DISPATCHED') {
    Object.assign(active, {
      status: 'RUNNING',
      started_at: now(),
      progress_date: active.requested_start_date,
    });
    db.startRevision.set(active.id, db.revision);
    return;
  }
  if (active?.status === 'RUNNING') {
    active.processed_days += 1;
    if (active.processed_days < active.total_days) {
      active.progress_date = addDays(active.requested_start_date, active.processed_days);
      return;
    }
    const finished = { finished_at: now(), progress_date: null };
    // An input changed during the run: publishing would overwrite current data (§10.2).
    if (db.revision !== db.startRevision.get(active.id)) {
      Object.assign(active, { status: 'SUPERSEDED', ...finished });
      return;
    }
    const start = active.requested_start_date;
    const end = active.requested_end_date;
    const predecessor = predecessorState(start);
    if (predecessor === 'STALE' || predecessor === 'NOT_PROCESSED') {
      db.issues.push({
        id: newId(),
        issue_type: 'STALE_PREDECESSOR',
        asset_id: null,
        asset_code: null,
        affected_date: start,
        required_price_date: null,
        request_id: active.id,
      });
    }
    const withIssues = db.issues.some((i) => i.affected_date >= start && i.affected_date <= end);
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

function enqueue(start: string, end: string): ProcessingRequest {
  const request: ProcessingRequest = {
    id: newId(),
    requested_start_date: start,
    requested_end_date: end,
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

export const processingHandlers = [
  http.get(url('/processing/requests'), async () => {
    await latency();
    tick();
    const items = [...db.requests].sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json<ListResponse<ProcessingRequest>>({ items });
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
    const errors = rangeErrors(start, end);
    if (errors.length > 0 || !start || !end) return problem(422, errors);

    return HttpResponse.json<ProcessingPreview>({
      start_date: start,
      end_date: end,
      total_days: daysInclusive(start, end),
      predecessor_date: addDays(start, -1),
      predecessor_state: predecessorState(start),
    });
  }),

  http.post(url('/processing/requests'), async ({ request }) => {
    await latency();
    const body = await readJson(request);
    const errors = rangeErrors(body.start_date, body.end_date);
    if (errors.length > 0) return problem(422, errors);
    return HttpResponse.json(enqueue(body.start_date as string, body.end_date as string), {
      status: 201,
    });
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
    const errors = rangeErrors(body.start_date, body.end_date);
    if (errors.length > 0) return problem(422, errors);
    const active = db.requests.find((r) => r.id === params.id);
    if (!active) return notFound('Processamento');
    if (!CANCELLABLE.includes(active.status)) return notCancellable();
    const response: CancelAndReplaceResponse = {
      cancelled: cancel(active),
      replacement: enqueue(body.start_date as string, body.end_date as string),
    };
    return HttpResponse.json(response, { status: 201 });
  }),

  http.get(url('/processing/issues'), async () => {
    await latency();
    const items = [...db.issues].sort((a, b) => b.affected_date.localeCompare(a.affected_date));
    return HttpResponse.json({ items });
  }),
];
