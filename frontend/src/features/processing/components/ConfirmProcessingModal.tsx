import { Button, Group, Modal, Skeleton, Stack } from '@mantine/core';
import { useRef } from 'react';

import type { ProcessingRangeRequest } from '@/api/contract';
import { ErrorState } from '@/shared/ui/ErrorState';

import { useEnqueue, usePreview } from '@/shared/processing/hooks';
import { PreviewSummary } from '@/shared/processing/PreviewSummary';
import { ActionError } from '@/shared/ui/ActionError';

interface ConfirmProcessingModalProps {
  /** The range to confirm; `null` keeps the modal closed. */
  range: ProcessingRangeRequest | null;
  onClose: () => void;
  /** The job was queued. */
  onQueued: () => void;
}

/**
 * "Confirmar processamento" (§10.1, OQ-11, OQ-21 draft): exactly [A, B], its days, its scope
 * and the state before it for each chain in scope.
 */
export function ConfirmProcessingModal({ range, onClose, onQueued }: ConfirmProcessingModalProps) {
  const preview = usePreview(range);
  const enqueue = useEnqueue();

  // One job per click, before `isPending` is rendered (§10.2). The modal cannot close while
  // the request runs, so the guard is always released by its outcome.
  const sending = useRef(false);

  const close = () => {
    // `sending` too: `isPending` reaches this render only after the click's render.
    if (enqueue.isPending || sending.current) return;
    enqueue.reset();
    onClose();
  };
  const confirm = () => {
    if (!range || sending.current) return;
    sending.current = true;
    enqueue.mutate(range, {
      onSuccess: () => {
        sending.current = false;
        enqueue.reset();
        onQueued();
      },
      onError: () => {
        sending.current = false;
      },
    });
  };

  return (
    <Modal
      opened={range !== null}
      onClose={close}
      title="Confirmar processamento"
      centered
      size="lg"
      closeOnEscape={!enqueue.isPending}
      closeOnClickOutside={!enqueue.isPending}
      withCloseButton={!enqueue.isPending}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      <Stack gap="md">
        {preview.isError ? (
          <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
        ) : preview.isPending || preview.isFetching ? (
          <Skeleton h={160} aria-busy="true" aria-label="Carregando pré-visualização" />
        ) : (
          <PreviewSummary preview={preview.data} />
        )}
        <ActionError error={enqueue.error} />
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close} disabled={enqueue.isPending}>
            Cancelar
          </Button>
          <Button
            onClick={confirm}
            loading={enqueue.isPending}
            disabled={!preview.isSuccess || preview.isFetching}
          >
            Confirmar processamento
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
