import type { MantineColor } from '@mantine/core';

import type { IsoDate, JobStatus, ProcessingRequest } from '@/api/contract';
import { addDays, daysInclusive } from '@/shared/format';

// Run statuses (spec §10.3, eight since OQ-23) with their pt-BR labels (OQ-20) and the colours of the
// Central de Controle design. The label is always shown: colour is never the only signal.

const BADGES: Record<JobStatus, { label: string; color: MantineColor }> = {
  QUEUED: { label: 'Na fila', color: 'gray' },
  DISPATCHED: { label: 'Enviado', color: 'blue' },
  RUNNING: { label: 'Processando', color: 'blue' },
  CANCELLING: { label: 'Cancelando', color: 'yellow' },
  CANCELLED: { label: 'Cancelado', color: 'gray' },
  COMPLETED: { label: 'Concluído', color: 'teal' },
  COMPLETED_WITH_ISSUES: { label: 'Concluído com pendências', color: 'yellow' },
  FAILED: { label: 'Falhou', color: 'red' },
};

export function jobStatusBadge(status: JobStatus): { label: string; color: MantineColor } {
  return BADGES[status];
}

const ACTIVE: readonly JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING', 'CANCELLING'];
const CANCELLABLE: readonly JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING'];
/** Ended before their last date: what is left of the range may be asked again (OQ-23). */
const UNFINISHED: readonly JobStatus[] = ['CANCELLED', 'FAILED'];

/** Work still to happen: the history is polled while any job is active (§12). */
export const isActive = (status: JobStatus) => ACTIVE.includes(status);

export const isFinal = (status: JobStatus) => !isActive(status);

/** Cancel, and cancel and replace (§10.2). */
export const canCancel = (status: JobStatus) => CANCELLABLE.includes(status);

/** "Solicitar novo processamento" from where the run stopped (OQ-20 item 4, OQ-23 item 10). */
export const canRequestAgain = (status: JobStatus) => UNFINISHED.includes(status);

/**
 * The date a run processes next, or failed on: the day after its last commit, or its start
 * (OQ-23). For a cancelled run, the first date it did not reach.
 */
export const nextDate = (job: ProcessingRequest): IsoDate =>
  job.progress_date === null ? job.start_date : addDays(job.progress_date, 1);

/** Days of the range and days committed, derived from the range and `progress_date` (OQ-23). */
export function progressOf(job: ProcessingRequest): { done: number; total: number } {
  return {
    done: job.progress_date === null ? 0 : daysInclusive(job.start_date, job.progress_date),
    total: daysInclusive(job.start_date, job.end_date),
  };
}
