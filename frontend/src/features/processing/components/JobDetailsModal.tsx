import { Alert, Button, Modal, Group, Progress, SimpleGrid, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import type { ProcessingChain, ProcessingRequest } from '@/api/contract';
import { formatDate, formatDateTime } from '@/shared/format';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { CHAIN_OF, SCOPE_LABELS } from '@/shared/processing/scope';

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
 * A Tudo run where one chain failed while the other went on (OQ-36): which chain stopped and
 * where, and, when it reached the end, that the other chain did.
 */
function failedChainNotice(job: ProcessingRequest, chain: ProcessingChain): string | null {
  if (job.failed_date === null) return null;
  const other: ProcessingChain = chain === 'CASH' ? 'POSITIONS' : 'CASH';
  const stopped = `O fechamento ${CHAIN_OF[chain]} falhou em ${formatDate(job.failed_date)}; suas datas seguintes não foram processadas.`;
  return job.status === 'COMPLETED_WITH_ISSUES'
    ? `${stopped} O fechamento ${CHAIN_OF[other]} foi processado até o fim do período.`
    : stopped;
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
          {chain !== null && (
            <Text size="sm" c="dimmed">
              {failedChainNotice(job, chain)}
            </Text>
          )}
          {(job.status === 'CANCELLED' || job.status === 'FAILED') && (
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
