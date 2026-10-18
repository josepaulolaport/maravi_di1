import type { JobStatus } from '@/api/contract';

import { canCancel, canRequestAgain, isActive, isFinal, jobStatusBadge } from './jobStatus';

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
    ['SUPERSEDED', 'Obsoleto', 'gray'],
  ])('§10.3 labels %s as "%s" in %s', (status, label, color) => {
    expect(jobStatusBadge(status)).toEqual({ label, color });
  });

  it('§11.1 polls only while a job is queued, dispatched, running or cancelling', () => {
    const active: JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING', 'CANCELLING'];
    const final: JobStatus[] = [
      'CANCELLED',
      'COMPLETED',
      'COMPLETED_WITH_ISSUES',
      'FAILED',
      'SUPERSEDED',
    ];
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
      'SUPERSEDED',
    ];
    for (const status of cancellable) expect(canCancel(status)).toBe(true);
    for (const status of notCancellable) expect(canCancel(status)).toBe(false);
  });

  it('OQ-20 offers a new request only for cancelled, failed or superseded jobs', () => {
    expect(canRequestAgain('CANCELLED')).toBe(true);
    expect(canRequestAgain('FAILED')).toBe(true);
    expect(canRequestAgain('SUPERSEDED')).toBe(true);
    expect(canRequestAgain('COMPLETED')).toBe(false);
    expect(canRequestAgain('COMPLETED_WITH_ISSUES')).toBe(false);
    expect(canRequestAgain('RUNNING')).toBe(false);
  });
});
