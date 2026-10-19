import { Alert, Button, Modal, Group, Progress, SimpleGrid, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import type { ProcessingChain, ProcessingRequest } from '@/api/contract';
import { addDays, formatDate, formatDateTime } from '@/shared/format';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { SCOPE_LABELS } from '@/shared/processing/scope';

import { formatDays, formatPeriod, shortId } from '../format';
import {
  canCancel,
  failedChainOf,
  jobStatusBadge,
  nextDate,
  progressOf,
  retryRequests,
} from '../jobStatus';
import { Field } from '@/shared/ui/Field';
import type { JobActions } from './HistoryTable';

/**
 * What a cancelled or failed run left published (OQ-23): every date up to its last commit
 * stays; later dates were not processed.
 */
function publishedNotice(job: ProcessingRequest): string {
  if (job.progress_date === null) {
    return 'Nenhuma data deste processamento foi publicada; os resultados anteriores permanecem inalterados.';
  }
  return `As datas de ${formatPeriod(job.start_date, job.progress_date)} foram publicadas; as seguintes não foram processadas.`;
}

/**
 * What each chain of a Tudo run with a failed chain left published (OQ-36 items 1 and 10): the
 * failed chain stopped the day before its `failed_date`; the other went on to `progress_date`,
 * the last date the run committed. Null for any other run, which `publishedNotice` covers.
 */
function chainNotices(job: ProcessingRequest): string[] | null {
  const { failed_chain: failed, failed_date: failedDate } = job;
  if (job.scope !== 'ALL' || failed === null || failedDate === null) return null;
  return (['CASH', 'POSITIONS'] as const).map((chain: ProcessingChain) => {
    const last =
      chain === failed
        ? failedDate > job.start_date
          ? addDays(failedDate, -1)
          : null
        : job.progress_date;
    const label = SCOPE_LABELS[chain];
    if (last === null) return `${label}: nenhuma data foi publicada.`;
    const published = `${label}: as datas de ${formatPeriod(job.start_date, last)} foram publicadas`;
    return last >= job.end_date
      ? `${published}.`
      : `${published}; as seguintes não foram processadas.`;
  });
}

/** A failed job without its message (the contract allows `null`). */
const FAILED_FALLBACK = 'Falha técnica inesperada.';

interface JobDetailsModalProps extends Omit<JobActions, 'onDetails'> {
  /** The job being followed (from the polled history); `null` keeps the modal closed. */
  job: ProcessingRequest | null;
  onClose: () => void;
}

/**
 * A run's details (§11.1, OQ-23): its range, times, days, progress, what it left published
 * and, if any, its error and the date it failed on.
 */
export function JobDetailsModal({ job, onClose, onCancel, onRequestAgain }: JobDetailsModalProps) {
  const progress = job ? progressOf(job) : null;
  const chain = job ? failedChainOf(job) : null;
  // Falhou, or a Tudo run that kept a chain's failure when it ended Concluído com pendências or
  // Cancelado (OQ-36 items 6 and 10).
  const failure = job !== null && (job.status === 'FAILED' || chain !== null);
  const perChain = job ? chainNotices(job) : null;
  return (
    <Modal
      opened={job !== null}
      onClose={onClose}
      title="Detalhes do processamento"
      centered
      size="lg"
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      {job && progress && (
        <Stack gap="md">
          <Group justify="space-between">
            <Text ff="monospace" fw={500}>
              {shortId(job.id)}
            </Text>
            <StatusBadge {...jobStatusBadge(job.status)} live />
          </Group>
          <Field label="Período solicitado">{formatPeriod(job.start_date, job.end_date)}</Field>
          <Field label="Escopo">{SCOPE_LABELS[job.scope]}</Field>
          <SimpleGrid cols={3}>
            <Field label="Criação">{formatDateTime(job.created_at)}</Field>
            <Field label="Início">{formatDateTime(job.started_at)}</Field>
            <Field label="Finalização">{formatDateTime(job.finished_at)}</Field>
          </SimpleGrid>
          <SimpleGrid cols={3}>
            <Field label="Total de dias">{formatDays(progress.total)}</Field>
            <Field label="Dias concluídos">{formatDays(progress.done)}</Field>
            {/* Counts of calendar days from the range and progress_date, never money. */}
            <Field label="Dias restantes">{formatDays(progress.total - progress.done)}</Field>
          </SimpleGrid>
          {(job.status === 'RUNNING' || job.status === 'CANCELLING') && (
            <Stack gap="xs">
              <Field label="Data em processamento">{formatDate(nextDate(job))}</Field>
              {/* Bar width only. */}
              <Progress.Root>
                <Progress.Section
                  aria-label="Progresso"
                  value={progress.total > 0 ? (progress.done / progress.total) * 100 : 0}
                />
              </Progress.Root>
            </Stack>
          )}
          {failure && (
            <>
              <SimpleGrid cols={2}>
                <Field label="Data com erro">{formatDate(job.failed_date ?? nextDate(job))}</Field>
                {job.failed_chain !== null && (
                  <Field label="Cadeia com erro">{SCOPE_LABELS[job.failed_chain]}</Field>
                )}
              </SimpleGrid>
              <Alert
                role="alert"
                color="red"
                variant="light"
                icon={<IconAlertTriangle size={18} />}
              >
                <Text size="sm">{job.error_message ?? FAILED_FALLBACK}</Text>
              </Alert>
            </>
          )}
          {perChain
            ? perChain.map((notice) => (
                <Text key={notice} size="sm" c="dimmed">
                  {notice}
                </Text>
              ))
            : (job.status === 'CANCELLED' || job.status === 'FAILED') && (
                <Text size="sm" c="dimmed">
                  {publishedNotice(job)}
                </Text>
              )}
          <Group justify="flex-end" gap="sm">
            {canCancel(job.status) && (
              <>
                <Button
                  color="red"
                  onClick={() => {
                    onCancel(job);
                  }}
                >
                  Cancelar processamento
                </Button>
              </>
            )}
            {retryRequests(job).map((retry) => (
              <Button
                key={retry.label}
                onClick={() => {
                  onRequestAgain(retry);
                }}
              >
                {retry.label}
              </Button>
            ))}
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
