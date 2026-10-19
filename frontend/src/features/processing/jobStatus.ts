import type { MantineColor } from '@mantine/core';

import type {
  IsoDate,
  JobStatus,
  ProcessingChain,
  ProcessingRequest,
  ProcessingScope,
} from '@/api/contract';
import { addDays, daysInclusive } from '@/shared/format';
import { SCOPE_LABELS } from '@/shared/processing/scope';

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

/**
 * Whether the user asked to cancel a run that is still running (OQ-46): the API keeps it
 * RUNNING with `cancel_requested_at` set until the current date commits.
 */
const isCancelling = (job: Pick<ProcessingRequest, 'status' | 'cancel_requested_at'>) =>
  job.status === 'RUNNING' && job.cancel_requested_at !== null;

/**
 * A run's badge: its status label, or Cancelando for a running run whose cancel was asked
 * (OQ-46, user decision). DISPATCHED and CANCELLING keep their labels but the API never sends
 * them since OQ-46.
 */
export function runBadge(job: Pick<ProcessingRequest, 'status' | 'cancel_requested_at'>): {
  label: string;
  color: MantineColor;
} {
  return isCancelling(job) ? BADGES.CANCELLING : BADGES[job.status];
}

const ACTIVE: readonly JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING', 'CANCELLING'];
/** Ended before their last date: what is left of the range may be asked again (OQ-23). */
const UNFINISHED: readonly JobStatus[] = ['CANCELLED', 'FAILED'];
/** Where a Tudo run may end with one chain failed and the other gone on (OQ-36, OQ-40). */
const CHAIN_FAILURE_ENDS: readonly JobStatus[] = ['COMPLETED_WITH_ISSUES', 'CANCELLED'];

/** Work still to happen: the history is polled while any job is active (§12). */
export const isActive = (status: JobStatus) => ACTIVE.includes(status);

export const isFinal = (status: JobStatus) => !isActive(status);

/**
 * Cancel (§10.2): a queued run, or a running one whose cancel was not asked yet; asking twice
 * answers 409 (OQ-46).
 */
export const canCancel = (job: Pick<ProcessingRequest, 'status' | 'cancel_requested_at'>) =>
  job.status === 'QUEUED' || (job.status === 'RUNNING' && !isCancelling(job));

/**
 * The date a run processes next, or failed on: the day after its last commit, or its start
 * (OQ-23). For a cancelled run, the first date it did not reach.
 */
export const nextDate = (job: ProcessingRequest): IsoDate =>
  job.progress_date === null ? job.start_date : addDays(job.progress_date, 1);

/**
 * The chain of a Tudo run that failed while the other went on (OQ-36): it ended Concluído com
 * pendências or Cancelado with `failed_chain` set. Null otherwise.
 */
export function failedChainOf(job: ProcessingRequest): ProcessingChain | null {
  return job.scope === 'ALL' && CHAIN_FAILURE_ENDS.includes(job.status) ? job.failed_chain : null;
}

/** A "Solicitar novo processamento" the run offers, with the request it prefills. */
export interface RetryRequest {
  label: string;
  start: IsoDate;
  end: IsoDate;
  scope: ProcessingScope;
}

/**
 * Where the plain retry starts (OQ-23 item 10): a failed run from its failed date, which on a
 * Tudo run whose chains failed on different dates is the first failure, before the chain that
 * failed later stopped; a cancelled run, or a failure with no date, from the first date not
 * reached.
 */
const retryStart = (job: ProcessingRequest): IsoDate =>
  job.status === 'FAILED' ? (job.failed_date ?? nextDate(job)) : nextDate(job);

/**
 * The new requests a finished run offers (OQ-20 item 4, OQ-23 item 10, OQ-40 items 3 and 6):
 * a cancelled or failed run, from where it stopped to its original end, in its scope; and a Tudo
 * run where one chain failed (Concluído com pendências or Cancelado), that chain alone from
 * `failed_date` to the original end.
 */
export function retryRequests(job: ProcessingRequest): RetryRequest[] {
  const requests: RetryRequest[] = [];
  if (UNFINISHED.includes(job.status)) {
    requests.push({
      label: 'Solicitar novo processamento',
      start: retryStart(job),
      end: job.end_date,
      scope: job.scope,
    });
  }
  const chain = failedChainOf(job);
  if (chain !== null && job.failed_date !== null) {
    requests.push({
      label: `Solicitar novo processamento (${SCOPE_LABELS[chain]})`,
      start: job.failed_date,
      end: job.end_date,
      scope: chain,
    });
  }
  return requests;
}

/** Days of the range and days committed, derived from the range and `progress_date` (OQ-23). */
export function progressOf(job: ProcessingRequest): { done: number; total: number } {
  return {
    done: job.progress_date === null ? 0 : daysInclusive(job.start_date, job.progress_date),
    total: daysInclusive(job.start_date, job.end_date),
  };
}
