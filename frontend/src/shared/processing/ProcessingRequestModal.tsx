import { Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import type { UseMutationResult } from '@tanstack/react-query';

import type {
  IsoDate,
  ProcessingRangeRequest,
  ProcessingRequest,
  ProcessingScope,
} from '@/api/contract';
import { useApiForm } from '@/shared/form/useApiForm';
import { useLastValue } from '@/shared/hooks/useLastValue';
import { ActionModal } from '@/shared/ui/ActionModal';
import { ErrorState } from '@/shared/ui/ErrorState';
import { FormActions } from '@/shared/ui/FormActions';
import { Loading } from '@/shared/ui/Loading';
import { MessageAlert } from '@/shared/ui/MessageAlert';

import { useEnqueue, usePreview } from './hooks';
import { PreviewSummary } from './PreviewSummary';
import { isValidRange } from './range';
import { RangeFields } from './RangeFields';
import { ScopeField } from './ScopeField';

export interface ProcessingDraft {
  start: IsoDate;
  end: IsoDate;
  scope: ProcessingScope;
}

interface DraftValues extends Record<string, unknown> {
  start: IsoDate | null;
  end: IsoDate | null;
  scope: ProcessingScope;
}

// API field → form field, for the problem+json errors (OQ-15).
const FIELD_MAP = { start_date: 'start', end_date: 'end', scope: 'scope' } as const;

interface ProcessingRequestModalProps {
  /** The prefilled request; `null` keeps the modal closed. */
  draft: ProcessingDraft | null;
  onClose: () => void;
  today: IsoDate;
  /** The notification once the job is queued. */
  queuedMessage: string;
}

/**
 * "Solicitar processamento" (§10.1, OQ-11, OQ-21), the one way to queue a job, from Central de
 * Controle and from Lançamentos: the range and scope, prefilled and editable, previewed as they
 * change (exactly [A, B], its days and the state before it per chain), then queued. The modal
 * stays open while the job is queued, so the outcome is always shown.
 */
export function ProcessingRequestModal({
  draft,
  onClose,
  today,
  queuedMessage,
}: ProcessingRequestModalProps) {
  const enqueue = useEnqueue();
  const shown = useLastValue(draft);
  const close = () => {
    enqueue.reset();
    onClose();
  };
  return (
    <ActionModal
      opened={draft !== null}
      onClose={close}
      title="Solicitar processamento"
      pending={enqueue.isPending}
    >
      {shown && (
        <RequestForm
          draft={shown}
          enqueue={enqueue}
          onClose={close}
          today={today}
          queuedMessage={queuedMessage}
        />
      )}
    </ActionModal>
  );
}

interface RequestFormProps {
  draft: ProcessingDraft;
  enqueue: UseMutationResult<ProcessingRequest, Error, ProcessingRangeRequest>;
  onClose: () => void;
  today: IsoDate;
  queuedMessage: string;
}

function RequestForm({ draft, enqueue, onClose, today, queuedMessage }: RequestFormProps) {
  const { form, pageErrors, onSubmit } = useApiForm<DraftValues>(
    { initialValues: { ...draft } },
    FIELD_MAP,
  );
  const { start, end, scope } = form.values;
  const range = start && end && isValidRange(start, end) ? { start, end } : null;
  const preview = usePreview(range && { start_date: range.start, end_date: range.end, scope });

  const submit = onSubmit(() =>
    range
      ? enqueue.mutateAsync({ start_date: range.start, end_date: range.end, scope }).then(() => {
          notifications.show({ color: 'teal', message: queuedMessage });
          onClose();
        })
      : undefined,
  );

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="md">
        <RangeFields
          start={start}
          end={end}
          onStartChange={(date) => {
            form.setFieldValue('start', date);
          }}
          onEndChange={(date) => {
            form.setFieldValue('end', date);
          }}
          maxDate={today}
          startError={form.errors.start}
          endError={form.errors.end}
        />
        <ScopeField
          value={scope}
          onChange={(next) => {
            form.setFieldValue('scope', next);
          }}
          disabled={enqueue.isPending}
          error={form.errors.scope}
        />
        {range === null ? (
          <Text size="sm" c="dimmed">
            Informe um intervalo válido para ver o que será processado.
          </Text>
        ) : preview.isError ? (
          <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
        ) : preview.isPending || preview.isFetching ? (
          <Loading label="Carregando pré-visualização" h={160} />
        ) : (
          <PreviewSummary preview={preview.data} />
        )}
        <MessageAlert messages={pageErrors} />
        <FormActions
          submitLabel="Confirmar processamento"
          onCancel={onClose}
          pending={enqueue.isPending}
          disabled={!preview.isSuccess || preview.isFetching}
        />
      </Stack>
    </form>
  );
}
