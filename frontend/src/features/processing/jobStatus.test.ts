import type { JobStatus, ProcessingRequest } from '@/api/contract';

import {
  canCancel,
  isActive,
  isFinal,
  jobStatusBadge,
  runBadge,
  nextDate,
  progressOf,
  retryRequests,
} from './jobStatus';

describe('job status (§10.3, OQ-20)', () => {
  it.each<[JobStatus, string, string]>([
    ['QUEUED', 'Na fila', 'gray'],
    ['DISPATCHED', 'Enviado', 'blue'],
    ['RUNNING', 'Processando', 'blue'],
    ['CANCELLING', 'Cancelando', 'yellow'],
    ['CANCELLED', 'Cancelado', 'gray'],
    ['COMPLETED', 'Concluído', 'teal'],
    ['COMPLETED_WITH_ISSUES', 'Concluído com pendências', 'yellow'],
    ['FAILED', 'Falhou', 'red'],
  ])('§10.3 labels %s as "%s" in %s', (status, label, color) => {
    expect(jobStatusBadge(status)).toEqual({ label, color });
  });

  it('§11.1 polls only while a job is queued, dispatched, running or cancelling', () => {
    const active: JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING', 'CANCELLING'];
    const final: JobStatus[] = ['CANCELLED', 'COMPLETED', 'COMPLETED_WITH_ISSUES', 'FAILED'];
    for (const status of active) {
      expect(isActive(status)).toBe(true);
      expect(isFinal(status)).toBe(false);
    }
    for (const status of final) {
      expect(isActive(status)).toBe(false);
      expect(isFinal(status)).toBe(true);
    }
  });

  const withCancel = (status: JobStatus, cancel_requested_at: string | null = null) =>
    ({ status, cancel_requested_at }) as ProcessingRequest;

  it('§10.2 OQ-46 cancels only a queued job, or a running one whose cancel was not asked yet', () => {
    expect(canCancel(withCancel('QUEUED'))).toBe(true);
    expect(canCancel(withCancel('RUNNING'))).toBe(true);
    expect(canCancel(withCancel('RUNNING', '2026-10-18T13:05:00Z'))).toBe(false);
    const ended: JobStatus[] = ['CANCELLED', 'COMPLETED', 'COMPLETED_WITH_ISSUES', 'FAILED'];
    for (const status of ended) expect(canCancel(withCancel(status))).toBe(false);
  });

  it('OQ-46 a running job with a cancel asked reads Cancelando; the API status stays RUNNING', () => {
    expect(runBadge(withCancel('RUNNING', '2026-10-18T13:05:00Z'))).toEqual({
      label: 'Cancelando',
      color: 'yellow',
    });
    expect(runBadge(withCancel('RUNNING'))).toEqual({ label: 'Processando', color: 'blue' });
    // A queued run cancelled at once is simply Cancelado.
    expect(runBadge(withCancel('CANCELLED', '2026-10-18T13:05:00Z'))).toEqual({
      label: 'Cancelado',
      color: 'gray',
    });
  });

  it('OQ-23 there are eight statuses: no SUPERSEDED (Obsoleto)', () => {
    expect(jobStatusBadge('SUPERSEDED' as JobStatus)).toBeUndefined();
  });

  const run = (changes: Partial<ProcessingRequest>) =>
    ({
      scope: 'ALL',
      start_date: '2026-10-14',
      end_date: '2026-10-18',
      progress_date: '2026-10-15',
      failed_date: null,
      failed_chain: null,
      ...changes,
    }) as ProcessingRequest;

  it('OQ-20 OQ-23 offers the plain new request only for cancelled or failed runs, from where they stopped', () => {
    const plain = {
      label: 'Solicitar novo processamento',
      start: '2026-10-16',
      end: '2026-10-18',
      scope: 'ALL',
    };
    expect(retryRequests(run({ status: 'CANCELLED' }))).toEqual([plain]);
    expect(retryRequests(run({ status: 'FAILED' }))).toEqual([plain]);
    for (const status of ['COMPLETED', 'COMPLETED_WITH_ISSUES', 'RUNNING'] as const) {
      expect(retryRequests(run({ status }))).toEqual([]);
    }
  });

  it('OQ-40 a Concluído com pendências ALL run where a chain failed offers that chain from failed_date', () => {
    const job = run({
      status: 'COMPLETED_WITH_ISSUES',
      progress_date: '2026-10-18',
      failed_date: '2026-10-16',
      failed_chain: 'POSITIONS',
    });

    expect(retryRequests(job)).toEqual([
      {
        label: 'Solicitar novo processamento (Posições)',
        start: '2026-10-16',
        end: '2026-10-18',
        scope: 'POSITIONS',
      },
    ]);
  });

  it('OQ-40 a Cancelado ALL run where a chain failed offers the plain retry and the failed-chain retry', () => {
    const job = run({
      status: 'CANCELLED',
      progress_date: '2026-10-16',
      failed_date: '2026-10-15',
      failed_chain: 'CASH',
    });

    expect(retryRequests(job)).toEqual([
      {
        label: 'Solicitar novo processamento',
        start: '2026-10-17',
        end: '2026-10-18',
        scope: 'ALL',
      },
      {
        label: 'Solicitar novo processamento (Caixa)',
        start: '2026-10-15',
        end: '2026-10-18',
        scope: 'CASH',
      },
    ]);
  });

  it('OQ-23 OQ-40 a Falhou run is asked again from its failed date, in its scope only', () => {
    // Cash failed on 12/10 and positions on 15/10: the run committed up to 14/10.
    const job = run({
      status: 'FAILED',
      start_date: '2026-10-10',
      progress_date: '2026-10-14',
      failed_date: '2026-10-12',
      failed_chain: 'CASH',
    });

    expect(retryRequests(job)).toEqual([
      {
        label: 'Solicitar novo processamento',
        start: '2026-10-12',
        end: '2026-10-18',
        scope: 'ALL',
      },
    ]);
  });

  it('OQ-23 a Falhou run without a failed date falls back to the day after its last commit', () => {
    const job = run({ status: 'FAILED', progress_date: '2026-10-15', failed_date: null });

    expect(retryRequests(job).map((r) => r.start)).toEqual(['2026-10-16']);
  });

  it('OQ-47 a Falhou run that failed writing its end, every date committed, is asked again in full', () => {
    // Every date committed, then recording the run's end failed: PROCESSING_ERROR, no date.
    const job = run({
      status: 'FAILED',
      start_date: '2026-10-14',
      progress_date: '2026-10-18',
      failed_date: null,
      error_code: 'PROCESSING_ERROR',
    });

    expect(retryRequests(job)).toEqual([
      {
        label: 'Solicitar novo processamento',
        start: '2026-10-14',
        end: '2026-10-18',
        scope: 'ALL',
      },
    ]);
  });

  it('OQ-23 derives the days done and the next date from the range and progress_date', () => {
    const job = {
      start_date: '2026-10-14',
      end_date: '2026-10-16',
      progress_date: null,
    } as ProcessingRequest;

    expect(progressOf(job)).toEqual({ done: 0, total: 3 });
    expect(nextDate(job)).toBe('2026-10-14');
    expect(progressOf({ ...job, progress_date: '2026-10-15' })).toEqual({ done: 2, total: 3 });
    expect(nextDate({ ...job, progress_date: '2026-10-15' })).toBe('2026-10-16');
  });
});
