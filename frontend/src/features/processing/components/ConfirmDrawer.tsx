import { Alert, Button, Drawer, Group, Skeleton, Stack, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useRef } from 'react';

import type { ProcessingPreview, ProcessingRangeRequest } from '@/api/contract';
import { formatDate } from '@/shared/format';
import { ErrorState } from '@/shared/ui/ErrorState';

import { formatDays, formatPeriod } from '../format';
import { useEnqueue, usePreview } from '../hooks/useProcessing';
import { ActionError } from './ActionError';
import { Field } from './Field';

interface ConfirmDrawerProps {
  /** The range to confirm; `null` keeps the drawer closed. */
  range: ProcessingRangeRequest | null;
  onClose: () => void;
  /** The job was queued. */
  onQueued: () => void;
}

/** "Confirmar processamento" (§10.1, OQ-11): exactly [A, B], its days and the state before it. */
export function ConfirmDrawer({ range, onClose, onQueued }: ConfirmDrawerProps) {
  const preview = usePreview(range);
  const enqueue = useEnqueue();

  // One job per click, before `isPending` is rendered (§10.2). The drawer cannot close while
  // the request runs, so the guard is always released by its outcome.
  const sending = useRef(false);

  const close = () => {
    if (enqueue.isPending) return;
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
    <Drawer
      opened={range !== null}
      onClose={close}
      title="Confirmar processamento"
      position="right"
      closeOnEscape={!enqueue.isPending}
      closeOnClickOutside={!enqueue.isPending}
      withCloseButton={!enqueue.isPending}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      <Stack gap="md">
        {preview.isError ? (
          <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
        ) : preview.isPending ? (
          <Skeleton h={160} aria-busy="true" aria-label="Carregando pré-visualização" />
        ) : (
          <PreviewSummary preview={preview.data} />
        )}
        <ActionError error={enqueue.error} />
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={close} disabled={enqueue.isPending}>
            Cancelar
          </Button>
          <Button onClick={confirm} loading={enqueue.isPending} disabled={!preview.isSuccess}>
            Confirmar processamento
          </Button>
        </Group>
      </Stack>
    </Drawer>
  );
}

function PreviewSummary({ preview }: { preview: ProcessingPreview }) {
  const predecessor = formatDate(preview.predecessor_date);
  return (
    <Stack gap="sm">
      <Field label="Período solicitado">{formatPeriod(preview.start_date, preview.end_date)}</Field>
      <Field label="Dias a processar">{formatDays(preview.total_days)}</Field>
      <Field label="Estado anterior">
        {preview.predecessor_state === 'ZERO_STATE' &&
          'Estado inicial (sem lançamentos anteriores)'}
        {preview.predecessor_state === 'VALID' && `Válido em ${predecessor.slice(0, 5)}`}
        {preview.predecessor_state === 'STALE' && 'Desatualizado'}
        {preview.predecessor_state === 'NOT_PROCESSED' && 'Não processado'}
      </Field>
      {(preview.predecessor_state === 'STALE' || preview.predecessor_state === 'NOT_PROCESSED') && (
        <Alert role="alert" color="yellow" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Text size="sm">
            {preview.predecessor_state === 'STALE'
              ? `O fechamento de ${predecessor} está desatualizado.`
              : `O dia ${predecessor} ainda não foi processado.`}{' '}
            O processamento será executado, mas os dias do intervalo aparecerão como desatualizados,
            sem P&L, e uma pendência pedirá o processamento de um intervalo anterior.
          </Text>
        </Alert>
      )}
    </Stack>
  );
}
