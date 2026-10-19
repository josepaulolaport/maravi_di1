import { Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useRef, useState } from 'react';

import type { IsoDate, ProcessingRequest, ProcessingScope } from '@/api/contract';
import { ApiError } from '@/api/http';

import { ScopeField } from '@/shared/processing/ScopeField';
import { SCOPE_LABELS } from '@/shared/processing/scope';

import { formatPeriod, shortId } from '../format';
import { useCancelAndReplace } from '../hooks/useProcessing';
import { ActionError } from '@/shared/ui/ActionError';
import { isValidRange, RangeFields } from '@/shared/processing/RangeFields';

/** The request's fields shown as inputs here: their API messages go on the inputs. */
const RANGE_FIELDS = ['start_date', 'end_date', 'scope'] as const;

interface ReplaceDialogProps {
  /** The active job to cancel; `null` keeps the dialog closed. */
  job: ProcessingRequest | null;
  onClose: () => void;
  today: IsoDate;
}

/**
 * "Cancelar e criar novo processamento" (§10.2, OQ-20 item 5): cancels the job and queues the
 * new range in one request. The range and scope start as the job's own and can be changed.
 */
export function ReplaceDialog({ job, onClose, today }: ReplaceDialogProps) {
  const replace = useCancelAndReplace();
  // It cannot close while the request runs, so its outcome (or error) is always shown.
  const close = () => {
    if (replace.isPending) return;
    replace.reset();
    onClose();
  };
  return (
    <Modal
      opened={job !== null}
      onClose={close}
      title="Cancelar e criar novo processamento"
      centered
      closeOnEscape={!replace.isPending}
      closeOnClickOutside={!replace.isPending}
      withCloseButton={!replace.isPending}
      closeButtonProps={{ 'aria-label': 'Fechar' }}
    >
      {/* Keyed by job, so the range restarts from each job's own. */}
      {job && (
        <ReplaceForm key={job.id} job={job} replace={replace} onClose={close} today={today} />
      )}
    </Modal>
  );
}

interface ReplaceFormProps {
  job: ProcessingRequest;
  replace: ReturnType<typeof useCancelAndReplace>;
  onClose: () => void;
  today: IsoDate;
}

function ReplaceForm({ job, replace, onClose, today }: ReplaceFormProps) {
  const [start, setStart] = useState<IsoDate | null>(job.requested_start_date);
  const [end, setEnd] = useState<IsoDate | null>(job.requested_end_date);
  const [scope, setScope] = useState<ProcessingScope>(job.scope);
  // One request per click, before `isPending` is rendered (two would queue two jobs, §10.2).
  const sending = useRef(false);
  const fieldErrors: Partial<Record<string, string>> =
    replace.error instanceof ApiError ? replace.error.fieldErrors() : {};

  const confirm = () => {
    if (!start || !end || !isValidRange(start, end) || sending.current) return;
    sending.current = true;
    replace.mutate(
      { requestId: job.id, range: { start_date: start, end_date: end, scope } },
      {
        onSuccess: () => {
          sending.current = false;
          replace.reset();
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
      <Text size="sm">
        O processamento {shortId(job.id)} (
        {formatPeriod(job.requested_start_date, job.requested_end_date)}, {SCOPE_LABELS[job.scope]})
        será cancelado e um novo processamento será colocado na fila com o intervalo e o escopo
        abaixo.
      </Text>
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
        disabled={replace.isPending}
        error={fieldErrors.scope}
      />
      <ActionError error={replace.error} shownOnFields={RANGE_FIELDS} />
      <Group justify="flex-end" gap="sm">
        <Button variant="default" onClick={onClose} disabled={replace.isPending}>
          Voltar
        </Button>
        <Button
          color="red"
          onClick={confirm}
          loading={replace.isPending}
          disabled={!isValidRange(start, end)}
        >
          Cancelar e criar novo
        </Button>
      </Group>
    </Stack>
  );
}
