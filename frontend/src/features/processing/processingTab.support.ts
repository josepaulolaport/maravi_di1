import { type BoundFunctions, type queries, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import type {
  PredecessorState,
  ProcessingPreview,
  ProcessingRequest,
  ProcessingScope,
} from '@/api/contract';
import { job, processingRequests } from '@/test/msw/fixtures';
import { url } from '@/test/msw/handlers';
import { server, serveJobs } from '@/test/msw/server';
import { renderApp } from '@/test/render';

// The history is the fixtures' five finished runs (src/test/msw/fixtures.ts): FAILED 01–05/10
// on its first date, CANCELLED 10–12/10 before its first date, COMPLETED 14–15/10, CANCELLED
// 14–16/10 after committing 14 and 15/10, COMPLETED_WITH_ISSUES 14–16/10. A test that follows
// a run scripts what the API reports on each poll (`serveJobs`); the preview and every write
// answer what the test serves.

export const PAGE = '/central-de-controle?tab=processamentos';

export function problemResponse(status: number, code: string, message: string) {
  return HttpResponse.json(
    { type: 'about:blank', title: 'Erro', status, errors: [{ code, message, field: null }] },
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );
}

/**
 * Serves `preview` as the API's answer to `GET /processing/preview` for its own range and
 * scope only; any other request gets an error, so a screen that asks for the wrong range or
 * scope fails the test.
 */
export function servePreview(preview: ProcessingPreview) {
  server.use(
    http.get(url('/processing/preview'), ({ request }) => {
      const params = new URL(request.url).searchParams;
      const asked = [params.get('start_date'), params.get('end_date'), params.get('scope')];
      const expected = [preview.start_date, preview.end_date, preview.scope];
      return asked.join() === expected.join()
        ? HttpResponse.json(preview)
        : problemResponse(500, 'VALIDATION_ERROR', `Prévia inesperada: ${asked.join(' ')}`);
    }),
  );
}

/** The preview of [start, end], whose day before is `before`, with each chain's state there. */
export function previewOf(
  start: string,
  end: string,
  before: string,
  totalDays: number,
  cash: PredecessorState,
  positions: PredecessorState,
  scope: ProcessingScope = 'ALL',
): ProcessingPreview {
  return {
    start_date: start,
    end_date: end,
    total_days: totalDays,
    scope,
    predecessor_date: before,
    predecessor: { cash, positions },
  };
}

/**
 * Answers each enqueue with the queued run, which the job list includes from then on. Records
 * the bodies; `gate` holds each answer until it resolves.
 */
export function answerEnqueue(jobs: { items: ProcessingRequest[] }, gate?: Promise<void>) {
  const bodies: unknown[] = [];
  server.use(
    http.post(url('/processing/requests'), async ({ request }) => {
      const body = (await request.json()) as Pick<
        ProcessingRequest,
        'start_date' | 'end_date' | 'scope'
      >;
      bodies.push(body);
      if (gate) await gate;
      const queued = job({
        ...body,
        id: `9a00000${bodies.length}-0000-4000-8000-000000000000`,
        created_at: `2026-10-18T11:0${bodies.length}:00-03:00`,
      });
      jobs.items = [queued, ...jobs.items];
      return HttpResponse.json(queued, { status: 201 });
    }),
  );
  return bodies;
}

/** Answers a cancel with `answer`, which the job list shows from then on. Counts the cancels. */
export function answerCancel(jobs: { items: ProcessingRequest[] }, answer: ProcessingRequest) {
  const cancels = { count: 0 };
  server.use(
    http.post(url('/processing/requests/:id/cancel'), () => {
      cancels.count += 1;
      jobs.items = jobs.items.map((j) => (j.id === answer.id ? answer : j));
      return HttpResponse.json(answer);
    }),
  );
  return cancels;
}

/** Serves `run` as the newest job, above the fixtures' history. */
export const serveWith = (...runs: ProcessingRequest[]) =>
  serveJobs([...runs, ...processingRequests]);

export const RUNNING = {
  status: 'RUNNING',
  dispatched_at: '2026-10-18T10:00:01-03:00',
  started_at: '2026-10-18T10:00:02-03:00',
  // 17/10 committed; 18/10 is being processed (OQ-23).
  progress_date: '2026-10-17',
} as const;

export function field(scope: BoundFunctions<typeof queries>, label: string) {
  return within(scope.getByRole('group', { name: label }));
}

export function history() {
  return within(screen.getByRole('region', { name: 'Histórico de processamentos' }));
}

export function jobRow(period: string, status: string) {
  const row = history()
    .getAllByRole('row')
    .find((r) => r.textContent.includes(period) && r.textContent.includes(status));
  if (!row) throw new Error(`no row ${period} ${status}`);
  return within(row);
}

/** `timeout` covers a poll (every 2 s) when the job must move on first. */
export async function findJobRow(period: string, status: string, timeout = 1_000) {
  await waitFor(() => jobRow(period, status), { timeout });
  return jobRow(period, status);
}

export async function closeMenu(user: ReturnType<typeof renderApp>['user']) {
  await user.keyboard('{Escape}');
  await waitFor(() => {
    expect(screen.queryByRole('menu')).toBeNull();
  });
}

export async function openMenu(
  user: ReturnType<typeof renderApp>['user'],
  period: string,
  status: string,
) {
  const row = await findJobRow(period, status);
  await user.click(row.getByRole('button', { name: /Ações do processamento/ }));
  await screen.findAllByRole('menuitem');
  return screen.getByRole('menu');
}

export async function typeRange(
  user: ReturnType<typeof renderApp>['user'],
  start: string,
  end: string,
  scope = within(document.body),
) {
  const first = scope.getByRole('textbox', { name: 'Data inicial' });
  const last = scope.getByRole('textbox', { name: 'Data final' });
  await user.clear(first);
  await user.type(first, start);
  await user.clear(last);
  await user.type(last, end);
}
