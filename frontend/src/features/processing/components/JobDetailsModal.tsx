import { Alert, Button, Modal, Group, Progress, SimpleGrid, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';

import type { ProcessingRequest } from '@/api/contract';
import { formatDate } from '@/shared/format';
import { StatusBadge } from '@/shared/ui/StatusBadge';

import { SCOPE_LABELS } from '@/shared/processing/scope';

import { formatDateTime, formatDays, formatPeriod, shortId } from '../format';
import { canCancel, canRequestAgain, jobStatusBadge, publishedNothing } from '../jobStatus';
import { Field } from '@/shared/ui/Field';
import type { JobActions } from './HistoryTable';

export const UNPUBLISHED_NOTICE =
  'Nenhum dia deste processamento foi publicado; os resultados anteriores permanecem inalterados.';

/** A FAILED job without its message (the contract allows `null`). */
const FAILED_FALLBACK = 'Falha técnica inesperada.';

interface JobDetailsModalProps extends Omit<JobActions, 'onDetails'> {
  /** The job being followed (from the polled history); `null` keeps the modal closed. */
  job: ProcessingRequest | null;
  onClose: () => void;
}

/** A job's details (§11.1): its range, times, days, progress and, if any, its error. */
export function JobDetailsModal({
  job,
  onClose,
  onCancel,
  onReplace,
  onRequestAgain,
}: JobDetailsModalProps) {
  return (
    <Modal
      opened={job !== null}
      onClose={onClose}
      title="Detalhes do processamento"
      centered
      size="lg"
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      {job && (
        <Stack gap="md">
          <Group justify="space-between">
            <Text ff="monospace" fw={500}>
              {shortId(job.id)}
            </Text>
            <StatusBadge {...jobStatusBadge(job.status)} live />
          </Group>
          <Field label="Período solicitado">
            {formatPeriod(job.requested_start_date, job.requested_end_date)}
          </Field>
          <Field label="Escopo">{SCOPE_LABELS[job.scope]}</Field>
          <SimpleGrid cols={3}>
            <Field label="Criação">{formatDateTime(job.created_at)}</Field>
            <Field label="Início">{formatDateTime(job.started_at)}</Field>
            <Field label="Finalização">{formatDateTime(job.finished_at)}</Field>
          </SimpleGrid>
          <SimpleGrid cols={3}>
            <Field label="Total de dias">{formatDays(job.total_days)}</Field>
            <Field label="Dias concluídos">{formatDays(job.processed_days)}</Field>
            {/* A count of calendar days, not a financial figure. */}
            <Field label="Dias restantes">{formatDays(job.total_days - job.processed_days)}</Field>
          </SimpleGrid>
          {(job.status === 'RUNNING' || job.status === 'CANCELLING') && (
            <Stack gap="xs">
              <Field label="Data em processamento">{formatDate(job.progress_date)}</Field>
              {/* Bar width only; the figures above are the API's. */}
              <Progress.Root>
                <Progress.Section
                  aria-label="Progresso"
                  value={job.total_days > 0 ? (job.processed_days / job.total_days) * 100 : 0}
                />
              </Progress.Root>
            </Stack>
          )}
          {job.status === 'FAILED' && (
            <Alert role="alert" color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
              <Text size="sm">{job.error_message ?? FAILED_FALLBACK}</Text>
            </Alert>
          )}
          {publishedNothing(job.status) && (
            <Text size="sm" c="dimmed">
              {UNPUBLISHED_NOTICE}
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
