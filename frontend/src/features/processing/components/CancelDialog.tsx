import { Stack, Text } from '@mantine/core';

import type { ProcessingRequest } from '@/api/contract';
import { ConfirmModal } from '@/shared/ui/ConfirmModal';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { formatPeriod } from '@/shared/format';

import { formatProgress, shortId } from '../model/format';
import { useCancel } from '../hooks/useProcessing';
import { runBadge, progressOf } from '../model/jobStatus';
import { useLastValue } from '@/shared/hooks/useLastValue';
import { Field } from '@/shared/ui/Field';

interface CancelDialogProps {
  /** The job to cancel; `null` keeps the dialog closed. */
  job: ProcessingRequest | null;
  onClose: () => void;
}

/**
 * "Cancelar processamento?" (§10.2): a queued job is cancelled at once, a running one
 * cooperatively, and the text says which. A job that already finished, or whose cancel was already asked (OQ-46), answers
 * 409 JOB_NOT_CANCELLABLE; its message is shown here.
 */
export function CancelDialog({ job, onClose }: CancelDialogProps) {
  const cancel = useCancel();
  // Still shown while the dialog closes.
  const shown = useLastValue(job);
  const close = () => {
    cancel.reset();
    onClose();
  };
  return (
    <ConfirmModal
      opened={job !== null}
      onClose={close}
      onConfirm={() => (job ? cancel.mutateAsync(job.id).then(close) : Promise.resolve())}
      title="Cancelar processamento?"
      confirmLabel="Confirmar cancelamento"
      loading={cancel.isPending}
      error={cancel.error}
    >
      {shown && (
        <Stack gap="sm">
          <Field label="Processamento">{shortId(shown.id)}</Field>
          <Field label="Período">{formatPeriod(shown.start_date, shown.end_date)}</Field>
          <Field label="Progresso">
            {formatProgress(progressOf(shown).done, progressOf(shown).total)}
          </Field>
          <Field label="Status atual">
            <StatusBadge {...runBadge(shown)} />
          </Field>
          <Text size="sm">
            {shown.status === 'QUEUED'
              ? 'O processamento ainda não começou e será cancelado imediatamente. Nenhuma data será processada.'
              : 'O processamento será interrompido ao fim da data em andamento. As datas já processadas continuam publicadas; as seguintes não serão processadas.'}
          </Text>
        </Stack>
      )}
    </ConfirmModal>
  );
}
