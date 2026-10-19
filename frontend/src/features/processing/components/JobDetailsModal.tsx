import { Alert, Button, Modal, Group, Progress, SimpleGrid, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import type { ProcessingRequest } from '@/api/contract';
import { formatDate, formatDateTime } from '@/shared/format';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { SCOPE_LABELS } from '@/shared/processing/scope';

import { formatDays, formatPeriod, shortId } from '../format';
import { canCancel, canRequestAgain, jobStatusBadge, nextDate, progressOf } from '../jobStatus';
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

/** A FAILED job without its message (the contract allows `null`). */
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
export function JobDetailsModal({
  job,
  onClose,
  onCancel,
  onReplace,
  onRequestAgain,
}: JobDetailsModalProps) {
  const progress = job ? progressOf(job) : null;
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
          {job.status === 'FAILED' && (
            <>
              <Field label="Data com erro">{formatDate(nextDate(job))}</Field>
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
          {canRequestAgain(job.status) && (
            <Text size="sm" c="dimmed">
              {publishedNotice(job)}
            </Text>
          )}
          <Group justify="flex-end" gap="sm">
            {canCancel(job.status) && (
              <>
                <Button
                  variant="default"
                  onClick={() => {
                    onReplace(job);
                  }}
                >
                  Cancelar e criar novo processamento
                </Button>
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
            {canRequestAgain(job.status) && (
              <Button
                onClick={() => {
                  onRequestAgain(job);
                }}
              >
                Solicitar novo processamento
              </Button>
            )}
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
