import type { MantineColor } from '@mantine/core';

import type { JobStatus } from '@/api/contract';

// Job statuses (spec §10.3) with their pt-BR labels (OQ-20) and the colours of the
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
  SUPERSEDED: { label: 'Obsoleto', color: 'gray' },
};

export function jobStatusBadge(status: JobStatus): { label: string; color: MantineColor } {
  return BADGES[status];
}

const ACTIVE: readonly JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING', 'CANCELLING'];
const CANCELLABLE: readonly JobStatus[] = ['QUEUED', 'DISPATCHED', 'RUNNING'];
/** All or nothing (§10.4): these published no day, so the same range may be asked again. */
const UNPUBLISHED: readonly JobStatus[] = ['CANCELLED', 'FAILED', 'SUPERSEDED'];

/** Work still to happen: the history is polled while any job is active (§12). */
export const isActive = (status: JobStatus) => ACTIVE.includes(status);

export const isFinal = (status: JobStatus) => !isActive(status);

/** Cancel, and cancel and replace (§10.2). */
export const canCancel = (status: JobStatus) => CANCELLABLE.includes(status);

/** "Solicitar novo processamento" with the full original range (OQ-20 item 4). */
export const canRequestAgain = (status: JobStatus) => UNPUBLISHED.includes(status);

/** A finished job that published nothing; earlier results stay as they were (§10.4). */
export const publishedNothing = canRequestAgain;
