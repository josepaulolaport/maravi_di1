import { Stack, Text } from '@mantine/core';

import type { ProcessingRequest } from '@/api/contract';
import { ConfirmModal } from '@/shared/ui/ConfirmModal';
import { StatusBadge } from '@/shared/ui/StatusBadge';

import { formatPeriod, formatProgress, shortId } from '../format';
import { useCancel } from '../hooks/useProcessing';
import { jobStatusBadge, progressOf } from '../jobStatus';
import { Field } from '@/shared/ui/Field';

interface CancelDialogProps {
  /** The job to cancel; `null` keeps the dialog closed. */
  job: ProcessingRequest | null;
  onClose: () => void;
}

/**
 * "Cancelar processamento?" (§10.2): a queued job is cancelled at once, a running one
 * cooperatively. A job that already finished answers 409 JOB_NOT_CANCELLABLE, shown here.
 */
export function CancelDialog({ job, onClose }: CancelDialogProps) {
  const cancel = useCancel();
  const close = () => {
    cancel.reset();
    onClose();
  };
  return (
    <ConfirmModal
      opened={job !== null}
      onClose={close}
      onConfirm={() => {
        if (job) cancel.mutate(job.id, { onSuccess: close });
      }}
      title="Cancelar processamento?"
      confirmLabel="Confirmar cancelamento"
      loading={cancel.isPending}
      error={cancel.error}
    >
      {job && (
        <Stack gap="sm">
          <Field label="Processamento">{shortId(job.id)}</Field>
          <Field label="Período">{formatPeriod(job.start_date, job.end_date)}</Field>
          <Field label="Progresso">
            {formatProgress(progressOf(job).done, progressOf(job).total)}
          </Field>
          <Field label="Status atual">
            <StatusBadge {...jobStatusBadge(job.status)} />
          </Field>
          <Text size="sm">
            O processamento será interrompido ao fim da data em andamento. As datas já processadas
            continuam publicadas; as seguintes não serão processadas.
          </Text>
        </Stack>
      )}
    </ConfirmModal>
  );
}
