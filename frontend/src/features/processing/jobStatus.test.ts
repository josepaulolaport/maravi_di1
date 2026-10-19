import type { JobStatus, ProcessingRequest } from '@/api/contract';

import {
  canCancel,
  isActive,
  isFinal,
  jobStatusBadge,
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

  it('§10.2 cancels (and cancels and replaces) only queued, dispatched or running jobs', () => {
    const cancellable: JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING'];
    const notCancellable: JobStatus[] = [
      'CANCELLING',
      'CANCELLED',
      'COMPLETED',
      'COMPLETED_WITH_ISSUES',
      'FAILED',
    ];
    for (const status of cancellable) expect(canCancel(status)).toBe(true);
    for (const status of notCancellable) expect(canCancel(status)).toBe(false);
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

  it('OQ-40 a Falhou run keeps the plain prefill, whatever its failed chain', () => {
    const job = run({
      status: 'FAILED',
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
