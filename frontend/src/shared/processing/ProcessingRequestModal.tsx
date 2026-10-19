import { Button, Group, Modal, Skeleton, Stack, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useRef, useState } from 'react';

import type { IsoDate, ProcessingScope } from '@/api/contract';
import { ApiError } from '@/api/http';
import { ActionError } from '@/shared/ui/ActionError';
import { ErrorState } from '@/shared/ui/ErrorState';

import { useEnqueue, usePreview } from './hooks';
import { PreviewSummary } from './PreviewSummary';
import { isValidRange, RangeFields } from './RangeFields';
import { ScopeField } from './ScopeField';

/** The request's fields shown as inputs here: their API messages go on the inputs. */
const SHOWN_FIELDS = ['start_date', 'end_date', 'scope'] as const;

export interface ProcessingDraft {
  start: IsoDate;
  end: IsoDate;
  scope: ProcessingScope;
}

interface ProcessingRequestModalProps {
  /** The prefilled request; `null` keeps the modal closed. */
  draft: ProcessingDraft | null;
  onClose: () => void;
  today: IsoDate;
}

/**
 * "Solicitar processamento" in place (§10.1, OQ-21 draft): the range and scope, prefilled and
 * editable, previewed as they change, then queued. The job is followed in Processamentos.
 */
export function ProcessingRequestModal({ draft, onClose, today }: ProcessingRequestModalProps) {
  const enqueue = useEnqueue();
  // It cannot close while the request runs, so its outcome (or error) is always shown.
  const close = () => {
    if (enqueue.isPending) return;
    enqueue.reset();
    onClose();
  };
  return (
    <Modal
      opened={draft !== null}
      onClose={close}
      title="Solicitar processamento"
      centered
      size="lg"
      closeOnEscape={!enqueue.isPending}
      closeOnClickOutside={!enqueue.isPending}
      withCloseButton={!enqueue.isPending}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      {draft && (
        <RequestForm
          key={`${draft.start}:${draft.end}:${draft.scope}`}
          draft={draft}
          enqueue={enqueue}
          onClose={close}
          today={today}
        />
      )}
    </Modal>
  );
}

interface RequestFormProps {
  draft: ProcessingDraft;
  enqueue: ReturnType<typeof useEnqueue>;
  onClose: () => void;
  today: IsoDate;
}

function RequestForm({ draft, enqueue, onClose, today }: RequestFormProps) {
  const [start, setStart] = useState<IsoDate | null>(draft.start);
  const [end, setEnd] = useState<IsoDate | null>(draft.end);
  const [scope, setScope] = useState<ProcessingScope>(draft.scope);
  const valid = isValidRange(start, end);
  const preview = usePreview(
    valid && start && end ? { start_date: start, end_date: end, scope } : null,
  );
  // One job per click, before `isPending` is rendered (two would queue two jobs, §10.2).
  const sending = useRef(false);
  const fieldErrors: Partial<Record<string, string>> =
    enqueue.error instanceof ApiError ? enqueue.error.fieldErrors() : {};

  const confirm = () => {
    if (!start || !end || !valid || sending.current) return;
    sending.current = true;
    enqueue.mutate(
      { start_date: start, end_date: end, scope },
      {
        onSuccess: () => {
          sending.current = false;
          notifications.show({
            color: 'teal',
            message: 'Processamento colocado na fila. Acompanhe em Central de Controle.',
          });
          enqueue.reset();
          onClose();
        },
        onError: () => {
          sending.current = false;
        },
      },
    );
  };

  return (
    <Stack gap="md">
      <RangeFields
        start={start}
        end={end}
        onStartChange={setStart}
        onEndChange={setEnd}
        maxDate={today}
        startError={fieldErrors.start_date}
        endError={fieldErrors.end_date}
      />
      <ScopeField
        value={scope}
        onChange={setScope}
        disabled={enqueue.isPending}
        error={fieldErrors.scope}
      />
      {!valid ? (
        <Text size="sm" c="dimmed">
          Informe um intervalo válido para ver o que será processado.
        </Text>
      ) : preview.isError ? (
        <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
      ) : preview.isPending || preview.isFetching ? (
        <Skeleton h={160} aria-busy="true" aria-label="Carregando pré-visualização" />
      ) : (
        <PreviewSummary preview={preview.data} />
      )}
      <ActionError error={enqueue.error} shownOnFields={SHOWN_FIELDS} />
      <Group justify="flex-end" gap="sm">
        <Button variant="default" onClick={onClose} disabled={enqueue.isPending}>
          Cancelar
        </Button>
        <Button
          onClick={confirm}
          loading={enqueue.isPending}
          disabled={!valid || !preview.isSuccess || preview.isFetching}
        >
          Confirmar processamento
        </Button>
      </Group>
    </Stack>
  );
}
